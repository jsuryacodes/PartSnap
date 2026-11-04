"""Live SAM 3.1 check on the hero photos: one "chipped wood edge" text prompt per image (outline.PROMPTS).
At most 2 paid calls; no point fallback.
Saves overlays + the accepted raw responses (mock format) to samples/hero/out/.
    cd backend && .venv/bin/python scripts/sam_live.py
Costs real credits: run once, don't loop it."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import models  # noqa: E402
import outline  # noqa: E402

HERO = Path(__file__).resolve().parents[2] / "samples" / "hero"
OUT = HERO / "out"


def main() -> int:
    models.MOCK_MODE = False
    OUT.mkdir(parents=True, exist_ok=True)
    real_call, raw = models.call, []

    def timed_call(*a, **kw):  # record latency + raw response of each SAM call
        t0 = time.time()
        r = real_call(*a, **kw)
        raw.append((time.time() - t0, r))
        return r

    models.call = timed_call
    found = 0
    for view in ("top", "front"):
        photo = (HERO / f"{view}.jpeg").read_bytes()
        img, size, scale = outline.prep_image(photo)
        print(f"\n== {view}.jpeg  {size[0]}x{size[1]} -> SAM {round(size[0] / scale[0])}x{round(size[1] / scale[1])}")
        raw.clear()
        try:
            r = outline.find_chip(photo, use_point=False, timeout=60)
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {str(e)[:500]}")
            continue
        for a, (secs, resp) in zip(r["attempts"], raw):
            u = resp.get("usage") or {}
            print(f"prompt    {a['prompt']!r}: {secs:.1f}s, tokens in={u.get('prompt_tokens')} "
                  f"out={u.get('completion_tokens')}, {len(a['matches'])} match(es), accepted={a['accepted']}")
            for m in a["matches"]:
                print(f"          score={m['score']} area={m['area_frac'] * 100:.2f}% of photo")
        o = r["outline"]
        if o:
            found += 1
            print(f"outline   {len(o['polygon'])} pts, area {o['area_px']:.0f} px, bbox {o['bbox']}, score {o['score']}")
            (OUT / f"sam_{view}.json").write_text(json.dumps([raw[-1][1]], indent=1) + "\n")
        outline.save_overlay(photo, o, OUT / f"{view}_overlay.png", view)
        print(f"overlay   {OUT / f'{view}_overlay.png'}")
    print(f"\n{found}/2 images outlined")
    return 0 if found == 2 else 1


if __name__ == "__main__":
    sys.exit(main())
