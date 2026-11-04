#!/usr/bin/env bash
# Serve the PartSnap backend from this Mac through a free Cloudflare quick tunnel, point Vercel at it and redeploy.
#   scripts/serve_public.sh            # (re)start everything; Ctrl-C (or kill the PID it prints) stops it
# Re-run after a reboot or a dropped tunnel: the quick-tunnel URL changes every time, and this redoes the Vercel
# env var + deploy. Live models (MOCK_MODE=0); keys come from backend/.env, which this script never reads.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/backend/.cache/serve"
FRONTEND_ORIGIN="https://partsnap-one.vercel.app"

# Keep the Mac awake for as long as this script runs.
if [ -z "${PARTSNAP_CAFFEINATED:-}" ]; then
  exec env PARTSNAP_CAFFEINATED=1 caffeinate -i "$0" "$@"
fi

mkdir -p "$LOGS"
echo "$$" > "$LOGS/serve.pid"

# A previous run may still hold the port or a stale tunnel.
pkill -f "uvicorn app:app --host 127.0.0.1 --port 8000" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://localhost:8000" 2>/dev/null || true
sleep 1

cleanup() { kill "${API_PID:-}" "${TUNNEL_PID:-}" 2>/dev/null || true; rm -f "$LOGS/serve.pid"; }
trap cleanup EXIT INT TERM

echo "== backend on 127.0.0.1:8000 (live models; rate limit + daily cap on)"
(cd "$ROOT/backend" && MOCK_MODE=0 DEV_FAKE_FAILURES=0 FRONTEND_ORIGIN="$FRONTEND_ORIGIN" \
  exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000) > "$LOGS/api.log" 2>&1 &
API_PID=$!
for _ in $(seq 60); do curl -sf -o /dev/null http://127.0.0.1:8000/docs && break; sleep 1; done
curl -sf -o /dev/null http://127.0.0.1:8000/docs || { echo "backend did not start; see $LOGS/api.log"; exit 1; }

echo "== cloudflare quick tunnel"
cloudflared tunnel --url http://localhost:8000 > "$LOGS/tunnel.log" 2>&1 &
TUNNEL_PID=$!
URL=""
for _ in $(seq 60); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGS/tunnel.log" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "no tunnel URL; see $LOGS/tunnel.log"; exit 1; }
for _ in $(seq 30); do curl -sf -o /dev/null "$URL/docs" && break; sleep 2; done  # DNS for a new tunnel takes a moment
echo "$URL" > "$LOGS/tunnel.url"

echo "== vercel: VITE_API_URL=$URL, redeploy"
cd "$ROOT/frontend"
vercel env rm VITE_API_URL production -y > /dev/null 2>&1 || true
printf '%s' "$URL" | vercel env add VITE_API_URL production > /dev/null 2>&1
DEPLOY="$(vercel deploy --prod --yes 2>&1 | grep -oE 'https://[a-z0-9-]+\.vercel\.app' | head -1)"
[ -n "$DEPLOY" ] || echo "!! vercel deploy printed no URL: run  cd frontend && vercel deploy --prod --yes  by hand"

echo
echo "tunnel:  $URL   (API docs: $URL/docs)"
echo "vercel:  $FRONTEND_ORIGIN   (deployment $DEPLOY)"
echo "logs:    $LOGS/{api,tunnel}.log; stop with Ctrl-C or: kill \$(cat $LOGS/serve.pid)"
wait "$API_PID" "$TUNNEL_PID"
