"""Spark Open writes CadQuery for a fix; verify; on failure send the error back (max 3 attempts).

run() yields progress events so the UI can stream each attempt, the model's reasoning, and verify results.
"""
import re

import models
from fixes import FIXES
from verify import verify

MAX_ATTEMPTS = 3
BY = "Muse Spark Open"

SYSTEM = """You write CadQuery (Python) code for 3D-printable repair parts.
Rules: units are mm; `import cadquery as cq`; hardcode the given measurements; assign the final
single solid to a variable named `result`; build it exactly in the coordinate frame described.
Reply with one ```python code block and nothing else."""


def _prompt(fix, params):
    mod = FIXES[fix]
    descs = {**mod.PARAMS, **getattr(mod, "OUTLINES", {})}
    lines = "\n".join(f"- {k} = {params[k]}  ({desc})" for k, desc in descs.items())
    return f"Fix type: {fix}\n{mod.__doc__.strip()}\n\nMeasurements:\n{lines}"


def _code(text):
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text


def run(fix: str, params: dict):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(fix, params)}]
    for n in range(1, MAX_ATTEMPTS + 1):
        yield {"type": "attempt", "n": n, "by": BY}
        resp = models.call("baseten", {"model": models.SPARK_OPEN, "messages": messages},
                           mock=f"spark_cad_{fix}", mock_vars=params)
        msg = resp["choices"][0]["message"]
        code = _code(msg["content"])
        yield {"type": "code", "n": n, "reasoning": msg.get("reasoning_content"), "code": code}
        result = verify(code, fix, params)
        yield {"type": "verify", "n": n, **result}
        if result["ok"]:
            yield {"type": "done", "ok": True, "stl_path": result["stl_path"], "mate_path": result["mate_path"], "attempts": n}
            return
        messages += [{"role": "assistant", "content": msg["content"]},
                     {"role": "user", "content": f"That code failed verification:\n{result['error']}\n"
                                                 "Fix it and return the full corrected code."}]
    yield {"type": "done", "ok": False, "attempts": MAX_ATTEMPTS}


if __name__ == "__main__":
    from fixes import chip_fill

    for fix, p in (("chip_fill", chip_fill.example()),
                   ("corner_cap", dict(edge_thickness=18, reach_x=40, reach_y=40, wall=2.5, clearance=0.2))):
        events = []
        for e in run(fix, p):
            events.append(e)
            print(fix, {k: v for k, v in e.items() if k not in ("code", "gaps")})
        verifies = [e for e in events if e["type"] == "verify"]
        if models.MOCK_MODE and models.DEV_FAKE_FAILURES:  # first mock attempt is deliberately wrong
            assert events[-1]["ok"] and len(verifies) == 2 and not verifies[0]["ok"], fix
        elif models.MOCK_MODE:
            assert events[-1]["ok"] and len(verifies) == 1, fix
    if models.MOCK_MODE:
        print(f"mock check passed (DEV_FAKE_FAILURES={int(models.DEV_FAKE_FAILURES)})")
