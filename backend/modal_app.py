"""Deploy the FastAPI backend to Modal.

    MOCK_MODE=1 FRONTEND_ORIGIN=https://<app>.vercel.app modal deploy modal_app.py

Keys come from the Modal secret `partsnap-keys` (META_API_KEY, BASETEN_API_KEY).
MOCK_MODE and FRONTEND_ORIGIN are read from your shell at deploy time; redeploy to flip them.
"""
import os

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0", "libxrender1")  # OpenCascade (CadQuery) runtime libs
    .pip_install_from_requirements("requirements.txt")
    .env({
        "MOCK_MODE": os.getenv("MOCK_MODE", "1"),
        "FRONTEND_ORIGIN": os.getenv("FRONTEND_ORIGIN", ""),
        "CACHE_DIR": "/data/cache",  # model-response cache + daily spend counter
        "OUT_DIR": "/data/out",  # generated STLs
    })
    .add_local_dir(".", "/root", ignore=[".venv", ".cache", "out", ".env", "__pycache__"])
)
volume = modal.Volume.from_name("partsnap-data", create_if_missing=True)
app = modal.App("partsnap", image=image)


@app.function(
    secrets=[modal.Secret.from_name("partsnap-keys")],
    volumes={"/data": volume},
    max_containers=1,  # rate limiter + spend counter + STL files assume a single container
    scaledown_window=300,  # scale to zero after 5 idle minutes
    # min_containers=1,  # uncomment during judging: no cold starts (bills while idle)
    timeout=600,
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app(label="partsnap-api")
def api():
    from app import app as fastapi_app

    return fastapi_app
