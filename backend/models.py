"""Every model call goes through call(): MOCK_MODE, disk cache keyed on input hash, token usage log."""
import base64
import hashlib
import json
import os
import threading
import time
from collections import Counter
from datetime import date
from pathlib import Path
from string import Template

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

MOCK_MODE = os.getenv("MOCK_MODE", "1") == "1"
CACHE = Path(os.getenv("CACHE_DIR", HERE / ".cache"))  # a Modal Volume in production
DAILY_CAP = int(os.getenv("DAILY_PAID_CALL_CAP", "300"))  # paid (live, uncached) model calls per day
MOCKS = HERE / "mocks"
MOCK_LATENCY = float(os.getenv("MOCK_LATENCY", "1.0"))
# Mock entries marked "fake": true (first CAD attempt broken, first photo check per view fails) are
# served only when this is on, to exercise the repair loop and the retake-guidance UI.
DEV_FAKE_FAILURES = os.getenv("DEV_FAKE_FAILURES", "0") == "1"
_mock_calls = Counter()

BASETEN_URL = "https://inference.baseten.co/v1/chat/completions"  # OpenAI-compatible
META_URL = "https://api.meta.ai/v1/responses"  # Responses API: the only Meta protocol that returns reasoning summaries

SPARK = "muse-spark-1.3"
WONDER = "muse-wonder-1.0"
SAM = "sam-3.1"
SPARK_OPEN = "meta-models/muse-spark-open-1026"  # Baseten. NOT meta-models/muse-spark-open


def _post(url, key_env, body, timeout):
    r = httpx.post(url, json=body, timeout=timeout, headers={"Authorization": f"Bearer {os.environ[key_env]}"})
    if r.is_error:  # keep the API's error message; raise_for_status() drops it
        raise httpx.HTTPStatusError(f"{r.status_code} from {url}: {r.text[:500]}", request=r.request, response=r)
    return r.json()


def _baseten(payload):
    """payload: an OpenAI chat-completions body, plus optional "timeout" (s)."""
    body = {k: v for k, v in payload.items() if k != "timeout"}
    return _post(BASETEN_URL, "BASETEN_API_KEY", body, payload.get("timeout", 300))


def _meta(payload):
    """payload (our neutral shape): {"model", "prompt", "images": [base64 JPEG], "effort", "schema",
    "max_output_tokens", "timeout"}; only model + prompt are required.
    Returns {"content", "reasoning" (summary text or None), "status", "usage": {"prompt_tokens",
    "completion_tokens", "reasoning_tokens"}}."""
    content = [{"type": "input_text", "text": payload["prompt"]}] + [
        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b}"} for b in payload.get("images", [])]
    body = {"model": payload["model"], "input": [{"type": "message", "role": "user", "content": content}],
            "store": False}
    if payload["model"] != SAM:  # SAM doesn't reason
        body["reasoning"] = {"effort": payload.get("effort", "low"), "summary": "auto"}
    if payload.get("metadata"):
        body["metadata"] = payload["metadata"]
    if payload.get("max_output_tokens"):
        body["max_output_tokens"] = payload["max_output_tokens"]  # includes reasoning tokens
    if payload.get("schema"):
        body["text"] = {"format": {"type": "json_schema", "name": "answer", "schema": payload["schema"]}}
    j = _post(META_URL, "MODEL_API_KEY", body, payload.get("timeout", 300))
    out = j.get("output") or []
    text = "".join(c.get("text", "") for o in out if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") == "output_text")
    reasoning = "\n".join(s.get("text", "") for o in out if o.get("type") == "reasoning" for s in o.get("summary", []))
    u = j.get("usage") or {}
    return {"content": text, "reasoning": reasoning or None, "status": j.get("status"),
            "usage": {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens"),
                      "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens")}}


PROVIDERS = {"baseten": _baseten, "meta": _meta}


class BudgetExceeded(Exception):
    pass


_spend_lock = threading.Lock()


def _spend():
    """Count one paid call against today's cap; the counter file lives next to the cache."""
    # ponytail: file + in-process lock assumes one container (modal_app sets max_containers=1)
    with _spend_lock:
        CACHE.mkdir(parents=True, exist_ok=True)
        f = CACHE / f"spend-{date.today()}.txt"
        n = int(f.read_text()) if f.exists() else 0
        if n >= DAILY_CAP:
            raise BudgetExceeded(f"daily cap of {DAILY_CAP} paid model calls reached")
        f.write_text(str(n + 1))


def call(provider: str, payload: dict, mock: str, mock_vars: dict | None = None) -> dict:
    """mock: name of mocks/<mock>.json, a list of responses. In MOCK_MODE the Nth response is
    returned, where N = number of assistant turns already in payload["messages"] (repair round).
    ${name} tokens in the mock file are filled from mock_vars (e.g. the user's measurements)."""
    t0 = time.time()
    source = "mock"
    if MOCK_MODE:
        raw = Template((MOCKS / f"{mock}.json").read_text()).safe_substitute(mock_vars or {})
        entries = [e for e in json.loads(raw) if DEV_FAKE_FAILURES or not e.get("fake")]
        if "messages" in payload:  # multi-turn (repair loop): one entry per assistant turn so far
            n = sum(m["role"] == "assistant" for m in payload["messages"])
        else:  # single-shot (photo check): Nth repeat of the same prompt, last entry once exhausted
            n = min(_mock_calls[mock, payload.get("prompt")], len(entries) - 1)
            _mock_calls[mock, payload.get("prompt")] += 1
        resp = entries[n]
        time.sleep(MOCK_LATENCY)  # so the UI's streaming is visible in demos
    else:
        try:
            resp, source = _cached_or_live(provider, payload)
        except httpx.HTTPError as e:  # covers timeouts and 4xx/5xx
            if payload.get("model") != WONDER:
                raise
            print(f"[model] fallback {WONDER} -> {SPARK} after: {str(e)[:300]}")
            payload = {**payload, "model": SPARK}
            resp, source = _cached_or_live(provider, payload)
    _log_usage(provider, payload.get("model"), source, resp.get("usage") or {}, time.time() - t0)
    return resp


def _cached_or_live(provider, payload):
    key = hashlib.sha256(json.dumps([provider, payload], sort_keys=True).encode()).hexdigest()
    f = CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text()), "cache"
    _spend()
    resp = PROVIDERS[provider](payload)
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(resp))
    return resp, "live"


def meta_json(prompt: str, images: list[bytes], mock: str, model: str = SPARK,
              effort: str = "low", schema: dict | None = None) -> dict:
    """Meta model call that must answer with a JSON object (schema-constrained when `schema` is given)."""
    payload = {"model": model, "prompt": prompt, "effort": effort,
               "images": [base64.b64encode(i).decode() for i in images]}
    if schema:
        payload["schema"] = schema
    text = call("meta", payload, mock)["content"].strip()
    return json.loads(text.removeprefix("```json").removeprefix("```").removesuffix("```"))


def sam(image_jpeg: bytes, text: str | None = None, box: tuple | None = None, points: list | tuple = (),
        mock: str = "sam", timeout: int = 300) -> dict:
    """SAM 3.1 on one image (JPEG bytes, already upright; see outline.prep_image).
    Prompt with a noun phrase `text`, OR a `box` (x1, y1, x2, y2 px, half-open) and/or `points`
    [(x, y, positive: bool)]; the API rejects mixing the two kinds.
    Returns {"image_size": (w, h), "usage", "objects": [{"id", "box": [x1, y1, x2, y2] half-open px,
    "score" (0-1 or None), "mask": (h, w) bool array, "contours": [[(x, y) px, ...], ...]}]}."""
    import io
    import numpy as np
    from meta_sam_parser import (CompletedOutcome, FramePrompt, PromptBox, PromptObject, PromptPoint,
                                 SegmentationMaskRecord, build_object_prompt, decode_mask_to_raster,
                                 decode_mask_to_svg_path, image_segmentation_format)
    from PIL import Image

    w, h = Image.open(io.BytesIO(image_jpeg)).size
    if bool(text) == bool(box or points):
        raise ValueError("give either a text prompt or box/points")
    prompt = text or build_object_prompt(size=(w, h), objects=[PromptObject(id=1, prompts=[FramePrompt(
        box=PromptBox(*box) if box else None,
        points=[PromptPoint(int(x), int(y), "positive" if pos else "negative") for x, y, pos in points])])])
    resp = call("meta", {"model": SAM, "prompt": prompt, "images": [base64.b64encode(image_jpeg).decode()],
                         "metadata": {"include_confidence": "true"}, "timeout": timeout}, mock)

    parser = image_segmentation_format().create_parser()
    parser.push(resp["content"])
    objects = []
    for rec in parser.finish(CompletedOutcome()).result.records:
        if not isinstance(rec, SegmentationMaskRecord):
            continue
        b, m = rec.bounds, rec.mask
        x0, y0, bw, bh = int(b.left), int(b.top), int(b.right - b.left), int(b.bottom - b.top)
        sx, sy = bw / m.width, bh / m.height  # the mask raster is box-local and smaller than the box
        local = np.frombuffer(decode_mask_to_raster(m), np.uint8).reshape(m.height, m.width)
        full = np.zeros((h, w), bool)
        full[y0:y0 + bh, x0:x0 + bw] = np.asarray(Image.fromarray(local * 255).resize((bw, bh), Image.NEAREST)) > 0
        contours = [[(x0 + (float(x) + 0.5) * sx, y0 + (float(y) + 0.5) * sy)  # raster pixel c spans c±0.5
                     for x, y in (pt.split() for pt in sub.strip().rstrip("Z").split("L"))]
                    for sub in decode_mask_to_svg_path(m).split("M") if sub.strip()]
        objects.append({"id": rec.object_id, "box": [x0, y0, x0 + bw, y0 + bh], "score": rec.confidence,
                        "mask": full, "contours": contours})
    return {"image_size": (w, h), "objects": objects, "usage": resp.get("usage")}


def _log_usage(provider, model, source, usage, secs):
    row = {"ts": round(time.time()), "provider": provider, "model": model, "source": source,
           "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
           "reasoning_tokens": usage.get("reasoning_tokens"), "secs": round(secs, 2)}
    print(f"[model] {json.dumps(row)}")
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(CACHE / "usage.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":  # offline self-check: no network, no keys used
    sent = {}

    def fake_post(url, json, timeout, headers):
        sent.update(url=url, body=json, timeout=timeout)
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "status": "completed",
            "output": [{"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "think"}]},
                       {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]}],
            "usage": {"input_tokens": 12, "output_tokens": 30, "output_tokens_details": {"reasoning_tokens": 28}}})

    httpx.post, os.environ["MODEL_API_KEY"] = fake_post, os.environ.get("MODEL_API_KEY", "test")
    r = _meta({"model": SPARK, "prompt": "hi", "images": ["AAAA"], "effort": "minimal",
               "schema": {"type": "object"}, "max_output_tokens": 150, "timeout": 60})
    b = sent["body"]
    assert sent["url"] == META_URL and sent["timeout"] == 60
    assert b["reasoning"] == {"effort": "minimal", "summary": "auto"} and b["max_output_tokens"] == 150
    assert b["input"][0]["content"][1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,AAAA"}
    assert b["text"]["format"]["type"] == "json_schema"
    assert r == {"content": "OK", "reasoning": "think", "status": "completed",
                 "usage": {"prompt_tokens": 12, "completion_tokens": 30, "reasoning_tokens": 28}}, r
    _meta({"model": SAM, "prompt": "chip", "metadata": {"include_confidence": "true"}})
    assert "reasoning" not in sent["body"] and sent["body"]["metadata"] == {"include_confidence": "true"}

    # Wonder failure -> one retry on Spark, through the real call() path (cache in a temp dir)
    import tempfile
    MOCK_MODE, CACHE, tried = False, Path(tempfile.mkdtemp()), []

    def flaky(p):
        tried.append(p["model"])
        if p["model"] == WONDER:
            raise httpx.ReadTimeout("simulated timeout")
        return {"content": "OK", "usage": {}}

    PROVIDERS["meta"] = flaky
    assert call("meta", {"model": WONDER, "prompt": "hi"}, mock="")["content"] == "OK"
    assert tried == [WONDER, SPARK], tried

    def down(p):
        tried.append(p["model"])
        raise httpx.ConnectError("down")

    PROVIDERS["meta"], tried[:] = down, []
    try:
        call("meta", {"model": SPARK, "prompt": "boom"}, mock="")
        raise AssertionError("a Spark error should propagate, not retry")
    except httpx.ConnectError:
        assert tried == [SPARK], tried

    # sam(): synthetic SAM output (a 40x20 px rectangle drawn at half resolution) decodes back to pixels
    import io
    from meta_sam_parser._mask_codec import _encode_raster
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 80)).save(buf, "JPEG")
    raster = [1] * (20 * 10)  # box-local raster: 20 wide, 10 high, for a 40x20 box
    PROVIDERS["meta"], CACHE = (lambda p: {"content": (
        "<0f>0<|box;x1=10;y1=30;x2=49;y2=49;w=100;h=80;c=0.91|>"
        f"<|mask;x=0;y=0;c=0.9;data=10,20,{_encode_raster(raster, 20, 10)}|>\n"), "usage": {}}), Path(tempfile.mkdtemp())
    s = sam(buf.getvalue(), text="thing")
    (o,) = s["objects"]
    assert s["image_size"] == (100, 80) and o["box"] == [10, 30, 50, 50] and o["score"] == 0.9, o
    assert o["mask"].sum() == 40 * 20 and o["mask"][30:50, 10:50].all()
    xs, ys = zip(*o["contours"][0])
    assert (min(xs), max(xs), min(ys), max(ys)) == (10, 50, 30, 50), (min(xs), max(xs), min(ys), max(ys))
    try:
        sam(buf.getvalue(), text="thing", points=[(1, 1, True)])
        raise AssertionError("mixing text and points should be rejected")
    except ValueError:
        pass
    print("models self-check passed")
