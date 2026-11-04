# PartSnap — Status Handoff (updated Wed Nov 4, 8:25 AM IST)

Read this first in any new chat. It supersedes older plans in hackathon-context.md where they conflict. Section "LOCKED (Nov 4 morning)" supersedes anything below it.

## Deadlines
- HARD deadline: **Thu Nov 5, 7:30 AM IST** (= Nov 4, 9 PM ET).
- Fixed point: full flow must produce **real STLs by Wed afternoon** so there's time to print + fit-test.
- Target: submit **Wed Nov 4 night**; post demo on X same night.

---

## 🔒 LOCKED (Nov 4 morning)

### Credits / infra
- **Using: Meta Model API ($150, claimed) + Baseten ($100).** That's enough.
- **No Modal credits** ($100 grant not received). Skip Modal. Optional fallback: pay ₹50 to unlock ~$30 only if the backend can't run on Render (CadQuery may be too heavy for Render's free tier).
- Backend deploy target: **Render** (or similar). Sandbox CadQuery in a subprocess on the backend host; note the trade-off in README.
- Muse Code: **not required**. Use it honestly for one small real task if there's spare time; mention in README.

### Meta API basics (from dev.meta.ai/docs/models)
- Base URL `https://api.meta.ai/v1`, auth `Authorization: Bearer $MODEL_API_KEY`. OpenAI-compatible; Responses, Chat Completions and Messages APIs.
- Wonder and Spark take the same requests on the same endpoints — switching = model ID change.
- Muse Spark Open is NOT on Model API — called via Baseten as `meta-models/muse-spark-open-1026`.

### Model per step
| Step | Model | Credits |
|---|---|---|
| Live photo checks (photos 1–2) | **Muse Spark Open** (Baseten) | Baseten |
| Outlines of the chip | **SAM 3.1** (`sam-3.1`, Responses API) | Meta |
| Diagnosis, deciding extra shots, deciding which measurements | **Muse Spark 1.3** (`muse-spark-1.3`) | Meta |
| Designing + repairing the fix (CadQuery) | **Muse Wonder** (`muse-wonder-1.0`, Meta's most capable model, preview) — fallback to `muse-spark-1.3` if Wonder errors | Meta |
| Independent review before STL release | **Muse Spark Open** (Baseten) | Baseten |
| (Optional) spoken measurements | Muse Voice Transcribe (`muse-voice-transcribe-1.0`) — NOT Spark 1.3 (audio degraded on 1.3) | Meta |
- Not using: Muse Glimmer (weaker, self-host only), Muse Image (preview is a real render instead).
- Cheaper Contributor mode IDs exist (e.g. `muse-spark-1.3-contributor`) — only if credits get tight.
- Watch Wonder cost: disk cache on, spend limit set, log tokens per call.

### User flow (locked)
1. **"Fix something"** — user starts.
2. **Photo 1 (top-down) + Photo 2 (front-on)** — analysed live; app keeps telling the user how to adjust ("move closer", "tilt down", "glare on the chip") until the angle is right; can't proceed until it passes.
   - Credit protection: **Cancel button** on every photo step; check a frame every **2–3 s** only when the phone is steady; checks run on **Spark Open via Baseten**; optional **"use this photo anyway"** after a few failed tries.
3. **Photo 3 (context)** — any wide shot of the table + damage; no strict check.
4. **Up to 3 extra shots** — models ask for specific angles only if they need more detail, and show the reason ("can't tell how far the chip goes down the front face — lower your phone to table height, shoot from the left at ~45°"). Extra/angled shots inform **diagnosis only, never geometry**.
5. **Measurements** — models mark the needed dimensions (A, B, C…) on the top and front photos; user measures with a ruler and types them in.
   - **No ruler in the photos.** The typed measurements set the pixel→mm scale.
   - Ask **2 measurements per view** so scale can be cross-checked; big mismatch = angled photo → ask for a retake.
   - Marker placement: SAM 3.1 outlines → **code** finds endpoints on the outline → Spark 1.3 picks which dimensions + writes labels. (LLMs are unreliable at raw pixel coordinates.)
   - For the hero chip, likely: length along the edge · max depth back on top · max depth down the front. Never ask to measure the feather edge.
6. **Build** — Wonder designs the fix → verify loop (watertight, size, collision, gaps) → repair up to 3× → Spark Open review → user gets a **print-ready STL + preview render** (real render of the generated part sitting in the chip, from the actual mesh).

### Architecture shape
- **Fixed stages, agent decisions inside them** (not a free-form orchestrator) — reliable for the live demo.
- Make agent decisions **visible in the UI** ("Agent: requesting another angle because…", verify failures + repair attempts, reasoning).

### Prize targets
- Indie track (main). Bonuses: **Best Agentic Use-Case** (visible agent loop: live guidance, extra-shot requests, measure requests, verify/repair, independent review) · **Best Build on Open Weights** (Spark Open as gatekeeper + reviewer) · **Best Creative Build** (eligible because Muse Wonder is used) · Most Viral · Community Vote.

---

## What's built (repo: https://github.com/jsuryacodes/PartSnap, public)
- React + Vite + TS frontend, deployed: https://partsnap-one.vercel.app (backend URL not set yet).
- Redesigned "engineering drawing / maker workshop" UI (paper bg, ink, safety-orange, mono labels). Landing + scroll-driven 3D /how-it-works page (7 steps).
- FastAPI backend (Python 3.12 venv in backend/.venv; system python is 3.15, unsupported by CadQuery).
- models.py: single call_model wrapper, disk cache, MOCK_MODE, token logging. Baseten client done (https://inference.baseten.co/v1/chat/completions, reasoning in message.reasoning_content). `_meta()` is a TODO stub — base URL/auth/model IDs now known (see above); still check image format + SAM request/response shape in the docs (Image understanding, Media segmentation).
- verify.py: sandboxed CadQuery run, watertight/size/overlap/per-face gap checks against a mating_solid(); repair loop up to 3 attempts.
- Fix types: corner_cap (done, verified) and chip_fill (requested; check repo for status).
- Whole flow runs end to end on mocks. **Nothing has run against a live model yet.**
- Rate limits + daily cap implemented.
- ⚠️ Existing code assumes ruler-in-photo scale + two photos — must change to the locked flow above.

## Hero demo object
- Black laminated particleboard/MDF table. Chip on the **front edge (not a corner)**.
- Shape: irregular trapezoid ~15–20 mm along the edge on top, ~4–6 mm back; on the front face a long shallow sliver, ~3–4 mm deep at one end tapering to a **feather edge**.
- Keep the shape **irregular** (looks real, shows off SAM).
- Photo conditions: dust wiped, side lamp (no overhead glare/phone shadow), no hand in shot. (Ruler no longer needed in frame.)
- Film the capture session — doubles as demo footage.

## Geometry approach for chip_fill
- SAM 3.1 outlines the exposed area in the top view and the front view.
- Scale from the user's typed measurements (cross-checked, see flow step 5).
- Build the piece as a **loft/ruled surface** from the back boundary of the top outline to the bottom boundary of the front outline (NOT intersection of two extrusions).
- Offset inward by clearance; enforce **min thickness 1.0 mm** (trim the feather edge, report trimmed amount).
- Verify against the damaged edge; export **two STLs: 0.2 mm and 0.4 mm clearance**. Print in **black PLA**.
- Manual tap-the-outline fallback if SAM is unreliable.

## Next steps (in order)
1. Keys into backend/.env (`MODEL_API_KEY`, Baseten key); implement `_meta()`; one live Spark 1.3 text call; one live Spark Open call.
2. SAM 3.1 outlines on hero photos (tap-outline fallback if poor).
3. Wonder CAD design + repair loop live; Spark 1.3 fallback.
4. Rework capture flow: live guided photos 1–2 + cancel, photo 3, up to 3 agent-requested shots.
5. Measurement step: annotated A/B/C overlays, scale from measurements + cross-check.
6. Spark Open review step; preview render.
7. Real run on the hero chip → two verified STLs → **send to printer** (printer status: **unconfirmed — check**).
8. Deploy backend (Render), set VITE_API_URL on Vercel.
9. README (architecture diagram, "Built during the hackathon", model chain, Muse Code credit if used), 3-min video, submission form, X post.
- Remove mock-only behaviour (forced first-attempt failure, always-pass photo check) in live mode; demo must show what really happens.

## Submission form notes
- Track: Indie Developer. Problem statement: Push the Frontier.
- Meta usage: Spark Open (live photo guidance + independent review, Baseten) → SAM 3.1 (outlines) → Muse Spark 1.3 (diagnosis, extra-shot requests, measurement selection) → Muse Wonder (designs + repairs CadQuery) → verify loop.
- Fill experience questions from real live-testing notes.
