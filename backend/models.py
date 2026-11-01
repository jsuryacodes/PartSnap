"""Every model call goes through call(): MOCK_MODE, disk cache keyed on input hash, token usage log."""
import base64
import hashlib
import json
import os
import time
from pathlib import Path
from string import Template

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

MOCK_MODE = os.getenv("MOCK_MODE", "1") == "1"
CACHE = HERE / ".cache"
MOCKS = HERE / "mocks"

BASETEN_URL = "https://inference.baseten.co/v1/chat/completions"  # OpenAI-compatible
SPARK_OPEN = "meta-models/muse-spark-open-1026"  # NOT meta-models/muse-spark-open
MUSE_SPARK = "TODO(user): Muse Spark model id from the Meta docs"


def _baseten(payload):
    r = httpx.post(BASETEN_URL, json=payload, timeout=300,
                   headers={"Authorization": f"Bearer {os.environ['BASETEN_API_KEY']}"})
    r.raise_for_status()
    return r.json()


def _meta(payload):
    """payload: {"model", "prompt", "images": [base64 JPEG]} (our own neutral shape).
    Must return {"content": <model text>, "usage": {"prompt_tokens", "completion_tokens"}}."""
    # TODO(user): paste the Meta Model API base URL + request/response format from the docs,
    # translate `payload` into it, and map the response to the shape above. Key: META_API_KEY.
    raise NotImplementedError("Meta Model API not wired yet: see TODO in models.py")


PROVIDERS = {"baseten": _baseten, "meta": _meta}


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
    else:
        key = hashlib.sha256(json.dumps([provider, payload], sort_keys=True).encode()).hexdigest()
        f = CACHE / f"{key}.json"
        if f.exists():
            resp, source = json.loads(f.read_text()), "cache"
        else:
            resp, source = PROVIDERS[provider](payload), "live"
            CACHE.mkdir(exist_ok=True)
            f.write_text(json.dumps(resp))
    _log_usage(provider, payload.get("model"), source, resp.get("usage") or {}, time.time() - t0)
    return resp


def meta_json(prompt: str, images: list[bytes], mock: str) -> dict:
    """Muse Spark call that must answer with a JSON object."""
    payload = {"model": MUSE_SPARK, "prompt": prompt,
               "images": [base64.b64encode(i).decode() for i in images]}
    text = call("meta", payload, mock)["content"].strip()
    return json.loads(text.removeprefix("```json").removeprefix("```").removesuffix("```"))


def _log_usage(provider, model, source, usage, secs):
    row = {"ts": round(time.time()), "provider": provider, "model": model, "source": source,
           "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
           "secs": round(secs, 2)}
    print(f"[model] {json.dumps(row)}")
    CACHE.mkdir(exist_ok=True)
    with open(CACHE / "usage.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
