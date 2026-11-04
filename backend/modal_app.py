"""PartSnap API on Modal: live models, one always-warm container, model cache + STLs on a Volume.

    scripts/deploy_backend.sh          # = cd backend && modal deploy modal_app.py

URL: https://penumatchajayasurya--partsnap-api.us-east.modal.run
Keys come from the Modal secret `partsnap-keys` (made from backend/.env); nothing else here is secret.
Code is uploaded from this directory on every deploy, so redeploy after any backend change.
"""
from pathlib import Path

import modal

HERE = Path(__file__).parent
FRONTEND_ORIGIN = "https://partsnap-one.vercel.app"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0", "libxrender1")  # OpenCascade (CadQuery) runtime libs
    .pip_install_from_requirements(str(HERE / "requirements.txt"))
    .env({
        "MOCK_MODE": "0",
        "DEV_FAKE_FAILURES": "0",
        "FRONTEND_ORIGIN": FRONTEND_ORIGIN,
        "GENERATIONS_PER_HOUR": "5",
        "DAILY_PAID_CALL_CAP": "300",
        "CACHE_DIR": "/data/cache",  # model-response cache, daily spend counter, agent log
        "OUT_DIR": "/data/out",  # generated STLs
    })
    .add_local_dir(HERE, "/root", ignore=[".venv", ".cache", "out", ".env", "__pycache__", "**/__pycache__"])
)
volume = modal.Volume.from_name("partsnap-data", create_if_missing=True)
app = modal.App("partsnap-api", image=image)


@app.function(
    secrets=[modal.Secret.from_name("partsnap-keys")],
    volumes={"/data": volume},
    cpu=2,
    memory=2048,
    min_containers=1,  # warm for the demo recording: no cold starts (bills while idle)
    max_containers=1,  # the per-IP rate limit and daily-cap counter are in-process
    timeout=600,  # /generate: Wonder up to 120 s x up to 3 attempts + verify
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app(label="partsnap-api")
def api():
    from app import app as fastapi_app

    async def committing(scope, receive, send):
        await fastapi_app(scope, receive, send)  # returns after the whole body (incl. SSE) is sent
        if scope["type"] == "http" and scope["method"] == "POST":  # POSTs write cache / STLs
            await volume.commit.aio()

    return committing
