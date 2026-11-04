"""Live connectivity check: exactly 4 tiny paid calls (Spark, Wonder, Spark Open text; Spark image).
Bypasses the cache, mocks and the Wonder->Spark fallback; still counts against the daily cap and logs usage.
    cd backend && .venv/bin/python scripts/smoke_live.py
Costs real credits: run once, don't loop it."""
import base64
import io
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import models  # noqa: E402

MAX_OUT, TIMEOUT = 150, 60


def test_image() -> str:
    img = Image.new("RGB", (512, 512), "white")
    ImageDraw.Draw(img).rectangle((156, 156, 356, 356), fill="red")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def meta(model, prompt, images=()):
    return "meta", {"model": model, "prompt": prompt, "images": list(images), "effort": "minimal",
                    "max_output_tokens": MAX_OUT, "timeout": TIMEOUT}


def baseten(prompt):
    return "baseten", {"model": models.SPARK_OPEN, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": MAX_OUT, "timeout": TIMEOUT}


def answer(provider, resp):
    """(text, reasoning text or None, usage) from either provider's response."""
    if provider == "meta":
        return resp["content"], resp["reasoning"], resp["usage"]
    msg = resp["choices"][0]["message"]
    u = resp.get("usage") or {}
    return msg.get("content") or "", msg.get("reasoning_content") or None, {
        "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}


def main() -> int:
    calls = [("text", *meta(models.SPARK, "Reply with OK")),
             ("text", *meta(models.WONDER, "Reply with OK")),
             ("text", *baseten("Reply with OK")),
             ("image", *meta(models.SPARK, "What colour is the square? Reply with one word.", [test_image()]))]
    failed = 0
    for kind, provider, payload in calls:
        print(f"\n== {payload['model']} ({provider}, {kind})")
        t0 = time.time()
        try:
            models._spend()
            resp = models.PROVIDERS[provider](payload)
        except Exception as e:  # report and move on; one model being down shouldn't hide the others
            failed += 1
            print(f"FAILED after {time.time() - t0:.1f}s: {type(e).__name__}: {str(e)[:500]}")
            continue
        secs = time.time() - t0
        text, reasoning, usage = answer(provider, resp)
        models._log_usage(provider, payload["model"], "live", usage, secs)
        print(f"latency   {secs:.1f}s" + (f"  status {resp['status']}" if resp.get("status") else ""))
        print(f"tokens    in={usage['prompt_tokens']} out={usage['completion_tokens']} "
              f"(reasoning={usage['reasoning_tokens']})")
        print(f"reasoning {'yes' if reasoning else 'no'}" + (f": {reasoning[:120]!r}" if reasoning else ""))
        print(f"answer    {text[:200]!r}")
    print(f"\n{len(calls) - failed}/{len(calls)} calls succeeded")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
