---
title: PartSnap API
emoji: 🔧
colorFrom: gray
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Photo + 3 measurements -> a 3D-printable fix (STL)
---

# PartSnap API

FastAPI backend for [PartSnap](https://partsnap-one.vercel.app) (source: https://github.com/jsuryacodes/PartSnap,
`backend/`). This Space is deployed from that folder with `git subtree push`; edit it on GitHub, not here.

- Secrets (Space settings): `MODEL_API_KEY` (Meta Model API), `BASETEN_API_KEY` (Spark Open on Baseten).
- Variables: `MOCK_MODE=0` for live models, `DEV_FAKE_FAILURES=0`.
- Limits: 5 generations per IP per hour, 300 paid model calls per day (both in-process; reset when the Space restarts).
- Disk is ephemeral: the model cache, spend counter and STLs live in `/tmp/partsnap`.
- Agent code runs in a subprocess with a 60 s CPU limit, an empty environment (no keys) and a timeout.

Docs: `/docs`.
