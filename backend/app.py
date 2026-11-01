"""PartSnap API. Run: .venv/bin/uvicorn app:app --port 8000 (frontend proxies /api here)."""
import inspect

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

import models
from fixes import FIXES

app = FastAPI(title="PartSnap")

MAX_PHOTO = 10 * 1024 * 1024
VIEWS = {
    "top": "a top-down view of the damaged corner, camera looking straight down, both edges visible",
    "side": "a side view of the edge, camera level with the tabletop, the thickness visible",
    "closeup": "a close-up of the damaged area, in focus and filling most of the frame",
}

CHECK_PROMPT = """You check photos for a repair app. The user was asked for: {want}.
Does the photo match that view, and is the damage clearly visible?
Answer with JSON only: {{"ok": true|false, "retake_instruction": null | "<one short sentence telling the user how to retake>"}}"""


async def _read(photo: UploadFile) -> bytes:
    data = await photo.read()
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "photo too large (max 10 MB)")
    return data


@app.post("/check-photo")
async def check_photo(view: str = Form(...), photo: UploadFile = File(...)):
    if view not in VIEWS:
        raise HTTPException(400, f"view must be one of {list(VIEWS)}")
    out = models.meta_json(CHECK_PROMPT.format(want=VIEWS[view]), [await _read(photo)], mock="check_photo")
    return {"ok": bool(out.get("ok")), "retake_instruction": out.get("retake_instruction"), "by": "Muse Spark"}


DIAGNOSE_PROMPT = """You diagnose damaged household objects for a 3D-printed repair app.
Photos, in order: top view, side view, close-up of the damage.
Available fix types:
{fixes}
Pick the fix type, explain the damage and the fix in 1–2 sentences, outline the damage on one photo,
and choose which of that fix's parameters the user must measure with a ruler (2–3, from its list).
For each, give a line on the photo where to measure, in 0–1 image coordinates.
Answer with JSON only:
{{"fix_type": str, "title": str, "explanation": str,
 "damage": {{"photo": "top"|"side"|"closeup", "polygon": [[x, y], ...]}},
 "measurements": [{{"key": str, "label": str, "hint": str, "photo": "top"|"side"|"closeup",
                   "line": [[x1, y1], [x2, y2]], "example": number}}]}}"""


@app.post("/diagnose")
async def diagnose(top: UploadFile = File(...), side: UploadFile = File(...), closeup: UploadFile = File(...)):
    # TODO(user): SAM 3.1 should supply the damage outline (and object mask) for the overlays; the mock
    # stands in for SAM + Muse Spark together. Wire SAM through models.call() once its host is chosen.
    fixes = "\n".join(f"- {k}: {m.__doc__.strip().splitlines()[0]} Parameters: {list(m.PARAMS)}" for k, m in FIXES.items())
    images = [await _read(f) for f in (top, side, closeup)]
    out = models.meta_json(DIAGNOSE_PROMPT.format(fixes=fixes), images, mock="diagnose")
    mod = FIXES.get(out.get("fix_type"))
    if mod is None:
        raise HTTPException(502, f"model picked an unknown fix type: {out.get('fix_type')!r}")
    out["measurements"] = [m for m in out.get("measurements", []) if m.get("key") in mod.PARAMS]
    measured = {m["key"] for m in out["measurements"]}
    # Parameters the user doesn't measure (wall, clearance) are print settings with defaults from make().
    out["settings"] = {k: v.default for k, v in inspect.signature(mod.make).parameters.items()
                       if k not in measured and v.default is not inspect.Parameter.empty}
    missing = set(mod.PARAMS) - measured - set(out["settings"])
    if missing:
        raise HTTPException(502, f"diagnosis did not ask for required measurements: {sorted(missing)}")
    out["param_help"] = mod.PARAMS
    out["by"] = {"diagnosis": "Muse Spark", "segmentation": "SAM 3.1"}
    return out
