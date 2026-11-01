# PartSnap

**Snap a photo of something broken. Print the part that fixes it.**

## Problem statement
**Push the Frontier: manufacturing & repair.** Small breakages, like a chipped table corner, usually get thrown away or left alone because designing a replacement part takes CAD skills. PartSnap turns a few guided photos and 2–3 ruler measurements into a verified, 3D-printable fix.

## How it works
1. **Guided capture**: a shot list (top view, side view, damage close-up) with ghost frames and a live tilt level.
2. **Photo check**: Muse Spark confirms each shot shows the right view and the damage, or asks for a retake.
3. **Segmentation**: SAM 3.1 isolates the object and the damage to draw "measure here" overlays.
4. **Diagnosis**: Muse Spark picks the fix type and the measurements it needs.
5. **CAD generation**: Muse Spark Open (Baseten) writes CadQuery code for the fix.
6. **Verify loop**: the code runs sandboxed. It is checked for watertightness, dimensions, and fit against the mating object, and failures are sent back for repair (max 3 attempts).
7. **Preview + download**: three.js preview and STL download.

MVP fix type: **corner cap**, an L-shaped cap that slides over a chipped tabletop corner.

## Setup
```
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # MOCK_MODE=1 runs the whole app on saved responses
.venv/bin/uvicorn app:app --port 8000
cd ../frontend && npm i && npm run dev   # open the Network URL on your phone
```

## Built during the hackathon (Oct 26 – Nov 4, 2026)
Everything in this repo was built during the Meta Global AI Developer Hackathon. The commit history is the build log.
