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


REVIEW = """You are an independent reviewer for PartSnap, which 3D-prints a piece to glue into a chip on a table's front \
edge. Another model (Muse Wonder) wrote the CAD; a geometric verifier built and measured it. Decide whether the piece \
should be released to the user for printing.

Frame (mm): x along the edge, y back into the table from the front face, z down from the tabletop. The user measured \
with a ruler: A = chip length along the edge, B = deepest point back on the tabletop, C = deepest point down the front.
Expected overall size: x = A - 2 x clearance - trimmed thin ends; y a little under B; z a little under C (the break \
surface is offset inward by the clearance, square to the sloped break).

{data}

Check: are the measurements plausible for a chipped table edge, does every verifier check pass, is each final size \
consistent with the measurements, does Wonder's rationale match what the verifier measured, is anything too thin or \
too small to print and glue? Reject only for a real problem the user should know about before printing. Keep your \
reasoning brief.

Answer with JSON only, no markdown: {{"verdict": "approve" | "reject", "notes": ["<one short sentence each, for the \
user>"]}}"""
REVIEW_MAX_TOKENS = 8000  # reasoning + JSON: a live run at 1500 spent all of it reasoning (finish_reason "length")
REVIEW_BY = "Muse Spark Open"


def review_data(params: dict, d: dict, results: list) -> dict:
    """What the reviewer sees: measurements, Wonder's answer, and each clearance's verify result (no code, no paths)."""
    keep = ("checks", "bbox", "expected_bbox", "gap", "min_thickness", "trimmed_mm", "interference_volume")
    return {"measurements_mm": {"A": params["edge_length_mm"], "B": params["top_depth_mm"], "C": params["front_depth_mm"]},
            "chosen_clearance_mm": params["clearance"],
            "wonder": {"rationale": d["rationale"], "declared_trimmed_mm": d["trimmed_mm"]},
            "verify": [{"clearance_mm": r["clearance"], **{k: r.get(k) for k in keep}} for r in results]}


def review(data: dict) -> dict:
    """Spark Open's advisory review. {"verdict": "approve"|"reject"|"unavailable", "notes", "reasoning", "usage",
    "by"}. Invalid JSON gets one retry (as a follow-up turn, so the cache doesn't replay it); a second failure or an
    API error is "unavailable"."""
    msgs = [{"role": "user", "content": REVIEW.format(data=json.dumps(data, indent=1))}]
    usage, reasoning = {}, None
    for _ in range(2):
        try:
            r = models.call("baseten", {"model": models.SPARK_OPEN, "messages": msgs, "max_tokens": REVIEW_MAX_TOKENS,
                                        "timeout": 120}, mock="spark_open_review")
        except Exception as e:  # incl. the daily budget: advisory, so release with an honest "unavailable"
            return {"verdict": "unavailable", "notes": [f"Review call failed: {str(e)[:200]}"], "reasoning": reasoning,
                    "usage": usage, "by": REVIEW_BY}
        c, u = r["choices"][0], r.get("usage") or {}
        m = c["message"]
        usage = {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                 "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}
        reasoning, text = m.get("reasoning_content"), (m.get("content") or "").strip()
        try:
            out = json.loads(text.removeprefix("```json").removeprefix("```").removesuffix("```"))
            notes = out["notes"]
            if out["verdict"] in ("approve", "reject") and isinstance(notes, list) and all(isinstance(n, str) for n in notes):
                return {"verdict": out["verdict"], "notes": notes, "reasoning": reasoning, "usage": usage, "by": REVIEW_BY}
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            pass
        if c.get("finish_reason") == "length":  # a retry would only be cut off again
            return {"verdict": "unavailable", "notes": ["The reviewer ran out of room before giving a verdict."],
                    "reasoning": reasoning, "usage": usage, "by": REVIEW_BY}
        msgs = msgs + [{"role": "assistant", "content": text},
                       {"role": "user", "content": 'That was not valid JSON. Answer with JSON only: '
                                                   '{"verdict": "approve" | "reject", "notes": [string]}'}]
    return {"verdict": "unavailable", "notes": ["The reviewer's answer was not valid JSON twice."], "reasoning": reasoning,
            "usage": usage, "by": REVIEW_BY}


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
            rv = review(review_data(params, d, results))
            _log({"run": run_id, "review": rv["verdict"], "notes": rv["notes"], "usage": rv["usage"]})
            yield {"type": "review", "run": run_id, **rv}
            yield {"type": "done", "ok": True, "attempts": n, "model": model, "rationale": d["rationale"],
                   "review": rv["verdict"], "run": run_id,
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

    (rv,) = [e for e in ev if e["type"] == "review"]
    assert rv["verdict"] == ev[-1]["review"] == ("reject" if models.DEV_FAKE_FAILURES else "approve"), rv

    real, seen = models.call, []  # review: bad JSON gets one follow-up turn, then "unavailable"; errors -> unavailable
    models.call = lambda prov, pl, **kw: seen.append(len(pl["messages"])) or {
        "choices": [{"message": {"content": "looks fine!", "reasoning_content": "hm"}}], "usage": {}}
    assert review({})["verdict"] == "unavailable" and seen == [1, 3], seen
    seen.clear()  # cut off mid-reasoning (finish_reason "length"): no retry, it would be cut off again
    models.call = lambda prov, pl, **kw: seen.append(1) or {
        "choices": [{"message": {"content": "", "reasoning_content": "hm"}, "finish_reason": "length"}], "usage": {}}
    assert review({})["verdict"] == "unavailable" and seen == [1], seen
    models.call = lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("slow"))
    assert review({})["verdict"] == "unavailable"
    models.call = lambda *a, **kw: {"choices": [{"message": {"content": '{"verdict": "maybe", "notes": []}'}}]}
    assert review({})["verdict"] == "unavailable"

    # a non-JSON answer is a failed attempt; three failures end the run with no STL
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
