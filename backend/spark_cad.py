"""Spark Open writes CadQuery for a fix; verify; on failure send the error back (max 3 attempts)."""
import re

import models
from fixes import FIXES
from verify import verify

MAX_ATTEMPTS = 3

SYSTEM = """You write CadQuery (Python) code for 3D-printable repair parts.
Rules: units are mm; `import cadquery as cq`; hardcode the given measurements; assign the final
single solid to a variable named `result`; build it exactly in the coordinate frame described.
Reply with one ```python code block and nothing else."""


def _prompt(fix, params):
    mod = FIXES[fix]
    lines = "\n".join(f"- {k} = {params[k]}  ({desc})" for k, desc in mod.PARAMS.items())
    return f"Fix type: {fix}\n{mod.__doc__.strip()}\n\nMeasurements:\n{lines}"


def _code(text):
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text


def generate(fix: str, params: dict) -> dict:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(fix, params)}]
    attempts = []
    for _ in range(MAX_ATTEMPTS):
        resp = models.call("baseten", {"model": models.SPARK_OPEN, "messages": messages}, mock="spark_cad")
        msg = resp["choices"][0]["message"]
        code = _code(msg["content"])
        result = verify(code, fix, params)
        attempts.append({"reasoning": msg.get("reasoning_content"), "code": code, "verify": result})
        if result["ok"]:
            return {"ok": True, "stl_path": result["stl_path"], "attempts": attempts}
        messages += [{"role": "assistant", "content": msg["content"]},
                     {"role": "user", "content": f"That code failed verification:\n{result['error']}\n"
                                                 "Fix it and return the full corrected code."}]
    return {"ok": False, "attempts": attempts}


if __name__ == "__main__":
    p = dict(edge_thickness=18, reach_x=40, reach_y=40, wall=2.5, clearance=0.2)
    out = generate("corner_cap", p)
    for i, a in enumerate(out["attempts"], 1):
        print(f"--- attempt {i}: ok={a['verify']['ok']} error={a['verify']['error']}")
        print(f"reasoning: {a['reasoning']}")
    print("RESULT:", out["ok"], out.get("stl_path"))
    if models.MOCK_MODE:  # the mock's first attempt is deliberately wrong, so this exercises repair
        assert out["ok"] and len(out["attempts"]) == 2 and not out["attempts"][0]["verify"]["ok"]
        print("mock repair loop check passed")
