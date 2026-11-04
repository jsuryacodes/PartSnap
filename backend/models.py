"""Every model call goes through call(): MOCK_MODE, disk cache keyed on input hash, token usage log."""
import base64
import hashlib
import json
import os
import threading
import time
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
            "reasoning": {"effort": payload.get("effort", "low"), "summary": "auto"}, "store": False}
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
        n = sum(m["role"] == "assistant" for m in payload.get("messages", []))
        raw = Template((MOCKS / f"{mock}.json").read_text()).safe_substitute(mock_vars or {})
        resp = json.loads(raw)[n]
        time.sleep(MOCK_LATENCY)  # so the UI's streaming is visible in demos
    else:
        key = hashlib.sha256(json.dumps([provider, payload], sort_keys=True).encode()).hexdigest()
        f = CACHE / f"{key}.json"
        if f.exists():
            resp, source = json.loads(f.read_text()), "cache"
        else:
            _spend()
            resp, source = PROVIDERS[provider](payload), "live"
            CACHE.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(resp))
    _log_usage(provider, payload.get("model"), source, resp.get("usage") or {}, time.time() - t0)
    return resp


def meta_json(prompt: str, images: list[bytes], mock: str, model: str = SPARK,
              effort: str = "low", schema: dict | None = None) -> dict:
    """Meta model call that must answer with a JSON object (schema-constrained when `schema` is given)."""
    payload = {"model": model, "prompt": prompt, "effort": effort,
               "images": [base64.b64encode(i).decode() for i in images]}
    if schema:
        payload["schema"] = schema
    text = call("meta", payload, mock)["content"].strip()
    return json.loads(text.removeprefix("```json").removeprefix("```").removesuffix("```"))


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
    print("models self-check passed")
