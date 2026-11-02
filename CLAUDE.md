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
    chip_fill.py  default: the exact missing piece, from SAM's top + side outlines (outlines_mm, missing_solid)
    corner_cap.py a cover that slides over the corner
  verify.py       sandboxed run + watertight / bbox / overlap / gap / fill-ratio checks + STL export (piece + mating object)
  models.py       all model calls: MOCK_MODE, disk cache, token logging
  mocks/          saved model responses for MOCK_MODE (diagnose.json is chip_fill; spark_cad_<fix>.json per fix)
  spark_cad.py    Spark Open -> CadQuery -> verify -> repair loop; run() yields progress events
  app.py          FastAPI: /check-photo, /diagnose, /generate (SSE), /stl/{name}
  export_how_it_works.py  writes frontend/public/hiw/*.stl + src/hiw.json (real chip_fill piece, table, prisms via verify.py); re-run if chip_fill or mocks/diagnose.json change
frontend/src/
  Landing -> Capture -> Measure -> Generate -> Result   one component per screen; api.ts holds all fetches
  HowItWorks.tsx  /how-it-works: lazy-loaded scroll-driven three.js explainer; still frames under reduced motion
  index.css       design tokens (paper/ink/safety-orange, IBM Plex Sans + Mono) and all styles; ui.tsx shared bits
```

## Commands
```
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --port 8000     # API (MOCK_MODE=1 unless backend/.env says otherwise)
.venv/bin/python verify.py                # self-check: hand-written corner cap
.venv/bin/python spark_cad.py             # Spark Open -> CadQuery -> verify loop
cd frontend && npm i && npm run dev       # HTTPS on the LAN for phones; /api proxies to :8000
HTTP=1 npx vite --port 5174               # plain HTTP for desktop browser testing
```

## Conventions
- API keys live only in `backend/.env` (gitignored). Never in the browser.
- Every model call goes through `models.py` (cache + mock + usage log). `MOCK_MODE=1` by default.
- Spark Open on Baseten: model `meta-models/muse-spark-open-1026` (NOT `meta-models/muse-spark-open`).
- Fix types: `chip_fill` (default for chipped corners/edges) and `corner_cap`. Don't add others yet.
- chip_fill outlines start at the corner, run along one face, follow the break, end on the other face (see its docstring).
- Units are millimetres.
- Commit after each working step with a clear message, then push. No Co-Authored-By trailers.
