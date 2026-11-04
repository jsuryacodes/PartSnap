#!/usr/bin/env bash
# Deploy backend/ to Modal (app partsnap-api). Run after every backend change: Modal serves the code from the last deploy.
#   scripts/deploy_backend.sh
# URL: https://penumatchajayasurya--partsnap-api.us-east.modal.run   Fallback host: scripts/serve_public.sh (Mac + tunnel).
set -euo pipefail
cd "$(dirname "$0")/../backend"
MODAL="$(command -v modal || echo .venv/bin/modal)"
"$MODAL" deploy modal_app.py
