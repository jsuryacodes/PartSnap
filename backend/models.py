"""Every model call goes through call(): MOCK_MODE, disk cache keyed on input hash, token usage log."""
import hashlib
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

MOCK_MODE = os.getenv("MOCK_MODE", "1") == "1"
CACHE = HERE / ".cache"
MOCKS = HERE / "mocks"

BASETEN_URL = "https://inference.baseten.co/v1/chat/completions"  # OpenAI-compatible
SPARK_OPEN = "meta-models/muse-spark-open-1026"  # NOT meta-models/muse-spark-open


def _baseten(payload):
    r = httpx.post(BASETEN_URL, json=payload, timeout=300,
                   headers={"Authorization": f"Bearer {os.environ['BASETEN_API_KEY']}"})
    r.raise_for_status()
    return r.json()


def _meta(payload):
    # TODO(user): paste the Meta Model API base URL + request/response format from the docs.
    # Uses META_API_KEY from .env. Used for Muse Spark (photo check, diagnosis).
    raise NotImplementedError("Meta Model API not wired yet: see TODO in models.py")


PROVIDERS = {"baseten": _baseten, "meta": _meta}


def call(provider: str, payload: dict, mock: str) -> dict:
    """mock: name of mocks/<mock>.json, a list of responses. In MOCK_MODE the Nth response is
    returned, where N = number of assistant turns already in payload["messages"] (repair round)."""
    t0 = time.time()
    source = "mock"
    if MOCK_MODE:
        n = sum(m["role"] == "assistant" for m in payload.get("messages", []))
        resp = json.loads((MOCKS / f"{mock}.json").read_text())[n]
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


def _log_usage(provider, model, source, usage, secs):
    row = {"ts": round(time.time()), "provider": provider, "model": model, "source": source,
           "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
           "secs": round(secs, 2)}
    print(f"[model] {json.dumps(row)}")
    CACHE.mkdir(exist_ok=True)
    with open(CACHE / "usage.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
