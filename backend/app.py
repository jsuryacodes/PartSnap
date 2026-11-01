"""PartSnap API. Run: .venv/bin/uvicorn app:app --port 8000 (frontend proxies /api here)."""
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

import models

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
