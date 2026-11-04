# PartSnap

Photograph a damaged object, give 2–3 ruler measurements, get a 3D-printable fix (STL) that fits.
Meta Global AI Developer Hackathon (Indie, solo). Deadline: Wed Nov 4 2026, 10 PM IST. Public repo; must use Meta models.

## Stack
- `frontend/`: React + Vite + TypeScript, mobile-first, deploys to Vercel (HTTPS for camera).
- `backend/`: Python 3.12 FastAPI + CadQuery, deploys to Modal/Render. Holds all API keys.

## Layout
```
backend/
  fixes/          one module per fix type (make, expected_bbox, mating_solid, PARAMS); registry in __init__.py
    chip_fill.py  default: the missing piece of a chipped edge, lofted between SAM's top + front outlines; helpers
                  (loft_between, offset_inward, enforce_min_thickness, mating_solid) the agent's code calls
    corner_cap.py a cover that slides over the corner
  verify.py       sandboxed run (fix helpers + params injected) + watertight / bbox / overlap / per-face gap (OCC
                  point distance) / min-thickness checks + STL export (piece + mating object)
  models.py       all model calls: MOCK_MODE, disk cache, token logging
  mocks/          saved model responses for MOCK_MODE (diagnose.json is chip_fill; spark_cad_<fix>.json per fix)
  spark_cad.py    Spark Open -> CadQuery -> verify -> repair loop; run() yields progress events
  app.py          FastAPI: /check-photo, /diagnose, /generate (SSE), /stl/{name}
frontend/src/
  Landing -> Capture -> Measure -> Generate -> Result   one component per screen; api.ts holds all fetches
  HowItWorks.tsx  /how-it-works: lazy-loaded scroll-driven three.js explainer; still frames under reduced motion
                  (its public/hiw assets are static and show the old corner/prism model; generator removed in Step 3)
  index.css       design tokens (paper/ink/safety-orange, IBM Plex Sans + Mono) and all styles; ui.tsx shared bits
```

## Commands
```
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --port 8000     # API (MOCK_MODE=1 unless backend/.env says otherwise)
.venv/bin/python -m fixes.chip_fill      # self-check: helpers on the hero outlines (MOCK_MODE=1 MOCK_LATENCY=0)
.venv/bin/python verify.py                # self-check: known-good / known-bad agent code, corner cap
.venv/bin/python spark_cad.py             # Spark Open -> CadQuery -> verify loop
cd frontend && npm i && npm run dev       # HTTPS on the LAN for phones; /api proxies to :8000
HTTP=1 npx vite --port 5174               # plain HTTP for desktop browser testing
```

## Conventions
- API keys live only in `backend/.env` (gitignored). Never in the browser.
- Every model call goes through `models.py` (cache + mock + usage log). `MOCK_MODE=1` by default.
- Spark Open on Baseten: model `meta-models/muse-spark-open-1026` (NOT `meta-models/muse-spark-open`).
- Fix types: `chip_fill` (default for chipped corners/edges) and `corner_cap`. Don't add others yet.
- chip_fill frame: origin at the chip's right (blunt) end on the top front edge; x left along the edge, y back into the
  table, z DOWN from the tabletop (STL prints tabletop face on the bed). Outlines are SAM px, scaled per view and axis
  by the measurements (see its docstring). samples/hero/measurements.json holds the hand-measured hero values.
- Units are millimetres.
- Commit after each working step with a clear message, then push. No Co-Authored-By trailers.
