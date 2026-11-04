"""PartSnap API. Run: .venv/bin/uvicorn app:app --port 8000 (frontend proxies /api here)."""
import base64
import inspect
import json
import os
import queue
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import models
import outline
import wonder_cad
from fixes import FIXES
from verify import OUT_DIR

app = FastAPI(title="PartSnap")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.getenv("FRONTEND_ORIGIN", "").split(",") if o],  # the Vercel domain
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)

BUDGET_MSG = "PartSnap has hit today's limit on AI calls (it's a hackathon demo on a budget). Please try again tomorrow!"
GEN_PER_HOUR = int(os.getenv("GENERATIONS_PER_HOUR", "5"))
_gens: dict[str, deque] = defaultdict(deque)


@app.exception_handler(models.BudgetExceeded)
def _budget(_req, _exc):
    return JSONResponse({"detail": BUDGET_MSG}, status_code=429)


def _rate_limit(request: Request):
    """Per-IP sliding window on /generate."""
    # ponytail: in-memory, so it assumes one container (modal_app sets max_containers=1)
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    now, q = time.time(), _gens[ip]
    while q and q[0] < now - 3600:
        q.popleft()
    if len(q) >= GEN_PER_HOUR:
        wait = int((q[0] + 3600 - now) / 60) + 1
        raise HTTPException(429, f"You've made {GEN_PER_HOUR} parts this hour. Please try again in about {wait} min.")
    q.append(now)

MAX_PHOTO = 10 * 1024 * 1024
VIEWS = {  # photos 1 and 2 are checked; the SAM frame (fixes/chip_fill.py) needs the edge level, placed as below
    "top": "a top view: camera straight above the chipped edge, looking straight down; the table's front edge runs "
           "left to right across the photo, level, in the lower part of the frame, with the chip on it",
    "side": "a front view: camera level with the tabletop, looking straight at the front face of the edge; the top "
            "edge runs left to right across the photo, level, with the chip on it",
}
CHECK_RULES = """- The view: {straight}.
- The chip is roughly centred and in focus.
- No glare or bright reflection on the chip.
- No hand or fingers in the photo.
- Close enough: the chip spans at least about a fifth of the photo's width."""
STRAIGHT = {"top": "straight above, looking down (not at an angle)", "side": "straight on, level with the tabletop"}

CHECK_PROMPT = """You check a photo for PartSnap, a repair app that 3D-prints the missing piece of a chipped table edge from
two photos (top and front) and the user's ruler measurements. The user was asked for: {want}.
Rules:
{rules}
Pass only if every rule holds. Keep your reasoning brief.
Answer with JSON only, no markdown: {{"ok": true|false, "retake_instruction": null | "<if not ok: one short sentence
telling the user what to change, e.g. 'Move closer so the chip fills more of the frame.'>", "rationale": "<one short
sentence for the user: what you saw>"}}"""
CHECK_BY = "Muse Spark Open"


def _check(view: str, jpeg: bytes) -> dict:
    """Spark Open (Baseten) checks one photo against the rules; returns its real reasoning too."""
    prompt = CHECK_PROMPT.format(want=VIEWS[view], rules=CHECK_RULES.format(straight=STRAIGHT[view]))
    image = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}
    r = models.call("baseten", {"model": models.SPARK_OPEN, "max_tokens": 4000, "timeout": 90, "messages": [
        {"role": "user", "content": [{"type": "text", "text": prompt}, image]}]}, mock="check_photo_open")
    m = r["choices"][0]["message"]
    text = (m.get("content") or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        out = json.loads(text)
        return {"ok": out["ok"] is True, "retake_instruction": out.get("retake_instruction"),
                "rationale": out.get("rationale"), "reasoning": m.get("reasoning_content"), "by": CHECK_BY}
    except (json.JSONDecodeError, KeyError, TypeError):
        raise HTTPException(502, "The photo check didn't give a clear answer. Check again, or retake the photo.")


async def _read(photo: UploadFile) -> bytes:
    data = await photo.read()
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "photo too large (max 10 MB)")
    return data


@app.post("/check-photo")
async def check_photo(view: str = Form(...), photo: UploadFile = File(...)):
    if view not in VIEWS:
        raise HTTPException(400, f"view must be one of {list(VIEWS)} (the context photo isn't checked)")
    return await run_in_threadpool(_check, view, await _read(photo))  # model calls block: keep the event loop free


DIAGNOSE_PROMPT = """You diagnose damaged household objects for a 3D-printed repair app.
Photos, in order: top view (looking down at the chipped edge), front view (looking at the edge's front face),
a context photo (stepped back: the whole edge and what's around it).
Available fix types (for a chipped edge, pick chip_fill unless the chip can't be filled):
{fixes}
Pick the fix type and explain the damage and the fix in 1–2 sentences. Choose which of that fix's parameters the user
must measure with a ruler (from its list; clearance is a print setting, not a measurement). The app draws where to
measure on the photos itself; for each you write a short label (2–4 words) and one short sentence for the user on why
the fix needs it.
{extra}
Answer with JSON only:
{{"fix_type": str, "title": str, "explanation": str, "rationale": "<one short sentence for the user: why this fix>",
 "measurements": [{{"key": str, "label": str, "hint": "<why we need this>", "example": number}}],
 "extra_shot": null | {{"what": "<one short sentence: what to photograph>", "reason": "<one short sentence: why it helps>"}}}}"""
EXTRA_ASK = """If the photos leave the diagnosis genuinely unclear (e.g. whether it is a clean chip, or what the material
is), you may ask for ONE extra photo in "extra_shot"; it is for the diagnosis only, never for sizes. Otherwise null."""
EXTRA_GOT = """A fourth photo is attached: the extra shot you asked for ("{what}"). Use it for the diagnosis.
Set "extra_shot" to null: no more photos."""


@app.post("/diagnose")
async def diagnose(top: UploadFile = File(...), side: UploadFile = File(...), closeup: UploadFile = File(...),
                   extra: UploadFile | None = File(None), extra_what: str = Form("")):
    """extra: the one extra photo Spark asked for (extra_shot) on a first call; at most one, so none is asked after."""
    fixes = "\n".join(f"- {k}: {m.__doc__.strip().splitlines()[0]} Parameters: {list(m.PARAMS)}" for k, m in FIXES.items())
    images = [await _read(f) for f in (top, side, closeup, extra) if f is not None]
    hint = EXTRA_GOT.format(what=extra_what[:200]) if extra else EXTRA_ASK
    out = await run_in_threadpool(models.meta_json, DIAGNOSE_PROMPT.format(fixes=fixes, extra=hint), images, mock="diagnose")
    ask = out.get("extra_shot")
    out["extra_shot"] = None if extra or not isinstance(ask, dict) or not ask.get("what") else \
        {"what": str(ask["what"]), "reason": str(ask.get("reason") or "")}
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
    # The chip's outlines come from SAM 3.1, never from the LLM (it can't place pixels reliably).
    found = {}
    for view, img, mock in (("top", images[0], "sam_top"), ("side", images[1], "sam_front")):
        found[view] = (await run_in_threadpool(outline.find_chip, img, mock=mock))["outline"]
        if found[view] is None:
            raise HTTPException(422, f"Couldn't find the chip in the {'top' if view == 'top' else 'front'} photo. "
                                     "Retake it closer, with the chip in the middle.")
    out["outlines"] = {v: [[x / o["image_size"][0], y / o["image_size"][1]] for x, y in o["polygon"]]
                       for v, o in found.items()}  # 0-1, for the overlay
    out["shape"] = {"top": found["top"], "front": found["side"]}  # px; /generate turns it into mm
    if hasattr(mod, "dimension_lines"):  # where to measure: computed from SAM's outlines, never LLM coordinates
        dims = mod.dimension_lines(out["shape"])
        out["extent_px"] = dims.pop("extent_px")  # the UI cross-checks the typed values' mm/px per view
        for m in out["measurements"]:
            d = dims[m["key"]]
            m |= {"letter": d["letter"], "photo": "side" if d["photo"] == "front" else d["photo"], "line": d["line"]}
        out["measurements"].sort(key=lambda m: list(mod.PARAMS).index(m["key"]))
    return out


@app.post("/outline")
async def chip_outline(view: str = Form(...), photo: UploadFile = File(...),
                       x: float | None = Form(None), y: float | None = Form(None)):
    """SAM 3.1 outline of the chip. x, y: optional tap on the chip (photo px) for the point-prompt fallback.
    outline is null when no plausible mask was found: the UI then asks the user to tap the outline."""
    if view not in ("top", "side"):
        raise HTTPException(400, "view must be top or side")
    data = await _read(photo)
    point = (x, y) if x is not None and y is not None else None
    return await run_in_threadpool(outline.find_chip, data, point, mock="sam_top" if view == "top" else "sam_front")


class TapOutline(BaseModel):
    points: list[list[float]]  # [[x, y], ...] in photo px, in tap order
    image_size: list[int]  # [w, h] of the photo the taps are on


@app.post("/outline/tap")
def tap_outline(req: TapOutline):
    """User-tapped fallback: same outline structure as /outline, so later steps don't care about the source."""
    if len(req.image_size) != 2 or min(req.image_size) <= 0:
        raise HTTPException(400, "image_size must be [w, h]")
    try:
        return {"outline": outline.from_taps(req.points, tuple(req.image_size)), "attempts": []}
    except ValueError as e:
        raise HTTPException(400, str(e))


class GenerateReq(BaseModel):
    fix: str
    params: dict[str, float]
    shape: dict | None = None  # from /diagnose, for fixes shaped from the photos


@app.post("/generate")
def generate(req: GenerateReq, request: Request):
    """Server-sent events: attempt / code / verify per attempt, then done."""
    if req.fix != "chip_fill":  # the CAD agent designs chip fills only
        raise HTTPException(400, f"only chip_fill can be generated, not {req.fix!r}")
    mod = FIXES[req.fix]
    if set(req.params) != set(mod.PARAMS):
        raise HTTPException(400, f"params must be exactly {sorted(mod.PARAMS)}")
    if not all(0 < v <= 1000 for v in req.params.values()) or req.params["clearance"] not in wonder_cad.CLEARANCES:
        raise HTTPException(400, "measurements must be in (0, 1000] mm and clearance 0.2 or 0.4 mm")
    params = dict(req.params)
    try:
        params |= mod.outlines_mm(req.shape or {}, **params)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as ex:
        raise HTTPException(400, f"could not read the photo outlines: {ex!r}")
    _rate_limit(request)
    url = lambda path: f"/stl/{Path(path).name}"  # never send server paths

    def produce(q: queue.Queue):
        try:
            for e in wonder_cad.run(params):
                for k in ("stl", "mate"):
                    if e.get(f"{k}_path"):
                        e[f"{k}_url"] = url(e.pop(f"{k}_path"))
                for s in e.get("stls", []):
                    s["url"] = url(s.pop("path"))
                q.put(e)
        except models.BudgetExceeded:
            q.put({"type": "error", "message": BUDGET_MSG})
        except Exception as ex:  # the stream has already started, so report errors as an event
            q.put({"type": "error", "message": f"Generation failed: {ex}"})
        q.put(None)

    def events():
        # The agent runs in a thread; an SSE comment every 15 s keeps proxies (Cloudflare drops a silent request
        # after ~100 s) from cutting the stream while Wonder thinks.
        q = queue.Queue()
        threading.Thread(target=produce, args=(q,), daemon=True).start()
        while True:
            try:
                e = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if e is None:
                return
            yield f"data: {json.dumps(e)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class Override(BaseModel):
    run: str


@app.post("/review-override")
def review_override(req: Override):
    """The user downloaded the STLs although Spark Open's review rejected them: on the record in the agent log."""
    if not re.fullmatch(r"[0-9a-f]{8}-\d+", req.run):
        raise HTTPException(400, "bad run id")
    wonder_cad._log({"run": req.run, "override": "downloaded despite review reject", "ts": round(time.time())})
    return {"ok": True}


@app.get("/stl/{name}")
def stl(name: str):
    path = OUT_DIR / name
    if not re.fullmatch(r"[\w-]+\.stl", name) or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="model/stl", filename="partsnap-fix.stl")
