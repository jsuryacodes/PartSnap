"""Muse Wonder designs the fix: it writes CadQuery that calls chip_fill's helpers, verify checks it, and failures go
back to Wonder for repair (max 3 attempts). Wonder falls back once to Muse Spark 1.3 on an API error or timeout.

run() yields progress events for the UI's agent log (attempt / design / verify per clearance / done) and logs every
attempt to stdout and .cache/agent_log.jsonl. A pass at the chosen clearance is re-verified at the other one; only
then are both STLs released. No fallback design, no pass without verify.
"""
import hashlib
import json
import time

import models
from fixes import chip_fill
from verify import verify

MAX_ATTEMPTS = 3
MAX_OUTPUT_TOKENS = 4000  # reasoning + the JSON answer
TIMEOUT_S = 120
CLEARANCES = (0.2, 0.4)
NAMES = {models.WONDER: "Muse Wonder", models.SPARK: "Muse Spark 1.3"}
LOG = models.CACHE / "agent_log.jsonl"

PROMPT = """You are PartSnap's CAD agent. Write CadQuery (Python) that builds a 3D-printable piece to glue into a chip \
on a table's front edge. Use the helpers below; do not model the geometry from scratch.

Frame (mm): origin at the chip's right (blunt) end, on the table's top front edge. x runs LEFT along the edge (the \
feather end is at x = {L}). y runs back into the table from the front face (y = 0). z runs DOWN into the table from \
the tabletop (z = 0). The table is y >= 0, z >= 0.

Already defined (don't redefine or import them): cq, TOP, FRONT, CLEARANCE = {c}, MIN_THICKNESS = 1.0, \
EDGE_LENGTH_MM, TOP_DEPTH_MM, FRONT_DEPTH_MM, and
- loft_between(top_back, front_bottom) -> solid: the missing piece, a ruled surface from the back boundary of the top \
outline ([x, y] points, ordered along x) to the bottom boundary of the front outline ([x, z] points), closed by the \
tabletop and front faces.
- offset_inward(solid, clearance) -> solid: moves the break surface in by `clearance` (true 3D offset); the tabletop \
and front faces stay flush.
- enforce_min_thickness(solid, min_mm) -> (solid, trimmed_mm): cuts the thin ends off so every cross-section is at \
least min_mm thick; trimmed_mm is the length removed along x.
- mating_solid(top, front) -> the damaged table, for checks only.

TOP, the chip seen from above (closed outline, [x, y] mm; y = 0 is the front edge): {top}
FRONT, the chip seen from the front (closed outline, [x, z] mm; z = 0 is the top edge): {front}
Measured: edge length {L} mm, top depth {DT} mm, front depth {DF} mm. At this clearance \
enforce_min_thickness(..., 1.0) removes {trim} mm: {blunt} mm at the blunt end, {feather} mm at the feather end.

Each outline goes from one end of the chip to the other and back: one side hugs the edge, the other follows the \
break. Pick the back boundary of TOP and the bottom boundary of FRONT, loft them, offset by CLEARANCE, enforce \
MIN_THICKNESS, and assign the final solid to `result`. Keep the outline points as they are: the irregular break is \
what makes the piece fit.

Answer with JSON only, no markdown: {{"code": "<python>", "rationale": "<1-2 plain sentences for the user: what you \
built and what you trimmed>", "fix_type": "chip_fill", "trimmed_mm": <number>}}"""

REPAIR = """

Attempt {n} failed. Your answer was:
{answer}

Verifier output:
{error}

Fix it and answer with the full corrected JSON only."""


def prompt(p: dict) -> str:
    r = chip_fill.reference(p["top"], p["front"], p["clearance"])
    pts = lambda poly: json.dumps([[round(a, 2), round(b, 2)] for a, b in poly])
    return PROMPT.format(L=p["edge_length_mm"], DT=p["top_depth_mm"], DF=p["front_depth_mm"], c=p["clearance"],
                         top=pts(p["top"]), front=pts(p["front"]), trim=r["trimmed_mm"], blunt=r["blunt_mm"],
                         feather=r["feather_mm"])


def parse(text: str) -> dict:
    """The answer, validated against {"code", "rationale", "fix_type": "chip_fill", "trimmed_mm"}; ValueError if not."""
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(t)
    except json.JSONDecodeError as e:
        raise ValueError(f"answer is not valid JSON ({e})")
    if not isinstance(d, dict):
        raise ValueError("answer must be a JSON object")
    bad = [k for k, ok in (("code", isinstance(d.get("code"), str) and d["code"].strip()),
                           ("rationale", isinstance(d.get("rationale"), str)),
                           ("fix_type", d.get("fix_type") == "chip_fill"),
                           ("trimmed_mm", type(d.get("trimmed_mm")) in (int, float))) if not ok]
    if bad:
        raise ValueError(f"answer has missing or wrong fields: {', '.join(bad)} (fix_type must be \"chip_fill\", "
                         "trimmed_mm a number)")
    return d


def _log(row: dict):
    print(f"[agent] {json.dumps(row)}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(row) + "\n")


def run(params: dict, max_attempts: int = MAX_ATTEMPTS):
    """params: chip_fill params incl. the mm outlines (outlines_mm) and clearance 0.2 or 0.4."""
    c = params["clearance"]
    other = next(x for x in CLEARANCES if x != c)
    base, feedback = prompt(params), ""
    ref = chip_fill.reference(params["top"], params["front"], c)
    mock_vars = {k: ref[k] for k in ("trimmed_mm", "blunt_mm", "feather_mm")}
    run_id = hashlib.sha256(base.encode()).hexdigest()[:8] + f"-{int(time.time())}"
    for n in range(1, max_attempts + 1):
        yield {"type": "attempt", "n": n, "by": NAMES[models.WONDER]}
        t0 = time.time()
        resp = models.call("meta", {"model": models.WONDER, "prompt": base + feedback, "effort": "low",
                                    "max_output_tokens": MAX_OUTPUT_TOKENS, "timeout": TIMEOUT_S},
                           mock="wonder_cad_chip_fill", mock_vars=mock_vars, mock_index=n - 1)
        model, usage, answer = resp["model"], resp.get("usage") or {}, resp.get("content") or ""
        row = {"run": run_id, "attempt": n, "model": model, "usage": usage, "call_secs": round(time.time() - t0, 1)}
        try:
            d = parse(answer)
        except ValueError as e:
            err = str(e)
            yield {"type": "design", "n": n, "model": model, "by": NAMES.get(model, model), "error": err, "usage": usage}
            yield {"type": "verify", "n": n, "ok": False, "error": err, "clearance": c, "checks": []}
            _log(row | {"code_hash": None, "failed": ["answer format"], "error": err, "rationale": None})
            feedback = REPAIR.format(n=n, answer=answer[:4000], error=err)
            continue
        code_hash = hashlib.sha256(d["code"].encode()).hexdigest()[:12]
        yield {"type": "design", "n": n, "model": model, "by": NAMES.get(model, model), "rationale": d["rationale"],
               "code": d["code"], "code_hash": code_hash, "trimmed_mm": d["trimmed_mm"], "usage": usage}
        first = verify(d["code"], "chip_fill", params | {"trimmed_mm": d["trimmed_mm"]})
        yield {"type": "verify", "n": n, **first}
        results, err = [first], first["error"]
        if first["ok"]:
            second = verify(d["code"], "chip_fill", params | {"clearance": other})
            yield {"type": "verify", "n": n, **second}
            results.append(second)
            err = None if second["ok"] else f"passed at {c} mm clearance but failed at {other} mm: {second['error']}"
        failed = sorted({k["name"] for r in results for k in r["checks"] if not k["ok"]} or ({"sandbox run"} if err else set()))
        _log(row | {"code_hash": code_hash, "failed": failed, "error": err and err[:600], "rationale": d["rationale"],
                    "trimmed_mm_declared": d["trimmed_mm"], "trimmed_mm": first.get("trimmed_mm"),
                    "verify_secs": round(time.time() - t0 - row["call_secs"], 1)})
        if not err:
            yield {"type": "done", "ok": True, "attempts": n, "model": model, "rationale": d["rationale"],
                   "trimmed_mm": first["trimmed_mm"], "mate_path": first["mate_path"],
                   "stls": sorted(({"clearance": r["clearance"], "path": r["stl_path"]} for r in results),
                                  key=lambda s: s["clearance"])}
            return
        feedback = REPAIR.format(n=n, answer=answer[:4000], error=err)
    yield {"type": "done", "ok": False, "attempts": max_attempts}


if __name__ == "__main__":  # offline self-check (MOCK_MODE): no model calls
    assert models.MOCK_MODE, "run with MOCK_MODE=1"
    p = chip_fill.example(clearance=0.2)
    assert "removes" in prompt(p) and len(prompt(p)) < 6000, len(prompt(p))

    def trace(events):
        out = []
        for e in events:
            out.append(e)
            print({k: (v if k not in ("code", "gaps", "checks") else "…") for k, v in e.items()})
        return out

    ev = trace(run(p))
    verifies = [e for e in ev if e["type"] == "verify"]
    want = 3 if models.DEV_FAKE_FAILURES else 2  # with fake failures: the no-offset attempt, then a repaired pass
    assert ev[-1]["ok"] and len(verifies) == want and [s["clearance"] for s in ev[-1]["stls"]] == [0.2, 0.4], ev[-1]
    assert not models.DEV_FAKE_FAILURES or (not verifies[0]["ok"] and "gap" in verifies[0]["error"])

    real = models.call  # a non-JSON answer is a failed attempt; three failures end the run with no STL
    models.call = lambda *a, **kw: {"content": "Sure! Here's the code:", "usage": {}, "model": models.WONDER}
    ev = list(run(p, max_attempts=2))
    models.call = real
    assert ev[-1] == {"type": "done", "ok": False, "attempts": 2}, ev[-1]
    assert sum(e["type"] == "verify" and "not valid JSON" in e["error"] for e in ev) == 2
    for bad in ('{"code": "x", "rationale": "", "fix_type": "corner_cap", "trimmed_mm": 1}', "[1]",
                '{"code": "", "rationale": "", "fix_type": "chip_fill", "trimmed_mm": "3"}'):
        try:
            parse(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    print(f"wonder_cad mock check passed (DEV_FAKE_FAILURES={int(models.DEV_FAKE_FAILURES)})")
