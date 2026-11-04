"""Hero run of the CAD agent: Muse Wonder designs the chip fill, verify checks it, at most ONE repair.
At most 2 Wonder calls (+1 Spark 1.3 call per Wonder error or 120 s timeout), one at a time. No SAM calls: the hero
outlines come from the saved SAM responses. Measurements come from samples/hero/measurements.json.
    cd backend && .venv/bin/python scripts/wonder_live.py --mock        # free dry run on the mock answers
    cd backend && .venv/bin/python scripts/wonder_live.py               # LIVE: costs credits, ask before re-running
Writes samples/hero/out/wonder_run[-mock].json (agent log + checks) and, live, the two STLs + the mating table."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import models  # noqa: E402
import wonder_cad  # noqa: E402
from fixes import chip_fill  # noqa: E402

HERO = Path(__file__).resolve().parents[2] / "samples" / "hero"
OUT = HERO / "out"
PLACEHOLDER = {"edge_length_mm": 18.0, "top_depth_mm": 5.0, "front_depth_mm": 3.5}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clearance", type=float, default=0.2, choices=wonder_cad.CLEARANCES)
    ap.add_argument("--mock", action="store_true", help="mock Wonder answers, no credits")
    a = ap.parse_args()

    m = json.loads((HERO / "measurements.json").read_text())
    dims = {k: m.get(k) for k in PLACEHOLDER}
    if any(v is None for v in dims.values()):
        if not a.mock:
            print(f"fill {HERO / 'measurements.json'} first: {dims}")
            return 2
        dims = {k: v if v is not None else PLACEHOLDER[k] for k, v in dims.items()}
        print(f"measurements.json not filled; dry run uses placeholders {dims}")
    if not a.mock and not os.getenv("MODEL_API_KEY"):
        print("MODEL_API_KEY is not set (backend/.env)")
        return 2

    params = chip_fill.example(**dims, clearance=a.clearance)  # reads the saved SAM outlines in mock mode
    models.MOCK_MODE = a.mock
    ref = chip_fill.reference(params["top"], params["front"], a.clearance)
    print(f"{'MOCK' if a.mock else 'LIVE'} run: {dims}, clearance {a.clearance} mm")
    print(f"scale mm/px (along, across): {params['scale']}")
    print(f"reference trim {ref['trimmed_mm']} mm (blunt {ref['blunt_mm']}, feather {ref['feather_mm']}); "
          f"prompt {len(wonder_cad.prompt(params))} chars; Wonder max_output_tokens {wonder_cad.MAX_OUTPUT_TOKENS}, "
          f"timeout {wonder_cad.TIMEOUT_S}s")

    events = []
    for e in wonder_cad.run(params, max_attempts=2):  # one design + at most one repair
        events.append(e)
        if e["type"] == "design":
            print(f"\n== attempt {e['n']}: {e['by']} ({e['model']}), tokens {e['usage']}")
            print(f"   rationale: {e.get('rationale') or e.get('error')}")
            if e.get("code"):
                print(f"   code {e['code_hash']}, declared trimmed_mm {e['trimmed_mm']}:\n" +
                      "\n".join("     " + ln for ln in e["code"].strip().splitlines()))
        elif e["type"] == "verify":
            print(f"   verify @ {e['clearance']} mm: {'PASS' if e['ok'] else 'FAIL'}")
            for k in e["checks"]:
                print(f"     {'ok ' if k['ok'] else 'BAD'} {k['name']}: {k['value']}" +
                      (f" (expected {k['expected']})" if k["expected"] else ""))
            if e["error"]:
                print(f"   error: {e['error'][:1500]}")
    done = events[-1]

    tag = "-mock" if a.mock else ""
    OUT.mkdir(parents=True, exist_ok=True)
    if done["ok"] and not a.mock:
        for s in done["stls"]:
            dst = OUT / f"chip_fill-{round(s['clearance'] * 100):03d}.stl"
            shutil.copy(s["path"], dst)
            print(f"STL {s['clearance']} mm -> {dst}")
        shutil.copy(done["mate_path"], OUT / "chip_fill-table.stl")
    slim = [{k: v for k, v in e.items() if k != "gaps"} for e in events]
    (OUT / f"wonder_run{tag}.json").write_text(json.dumps({"measurements": dims, "clearance": a.clearance,
                                                           "events": slim}, indent=1) + "\n")
    print(f"\n{'PASS' if done['ok'] else 'FAIL'} after {done['attempts']} attempt(s); log {OUT / f'wonder_run{tag}.json'}")
    return 0 if done["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
