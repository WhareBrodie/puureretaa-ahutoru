#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"
VITE_PORT="${VITE_PORT:-5173}"
export PORT
export PURERETA_ROOT="$(pwd)"
export PUBLIC_URL="${PUBLIC_URL:-http://localhost:${PORT}}"

if command -v lsof >/dev/null 2>&1; then
  for p in "${PORT}" "${VITE_PORT}"; do
    stale_pids="$(lsof -ti tcp:"${p}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${stale_pids}" ]]; then
      echo "Stopping process on port ${p}..."
      kill ${stale_pids} 2>/dev/null || true
      sleep 0.5
    fi
  done
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm install)
fi

if [[ ! -d .venv ]]; then
  echo "Creating Python venv..."
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

cleanup() {
  kill "${API_PID:-}" "${VITE_PID:-}" "${SYNC_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Pūreretā Ahutoru sync worker starting..."
.venv/bin/python3 server/bambu/sync_worker.py &
SYNC_PID=$!

echo "Pūreretā Ahutoru API: http://localhost:${PORT}"
.venv/bin/python3 server/purereta_server.py &
API_PID=$!

echo "Pūreretā Ahutoru Vite dev: http://localhost:${VITE_PORT} (proxies /api → :${PORT})"
(cd frontend && npm run dev -- --port "${VITE_PORT}") &
VITE_PID=$!

echo ""
echo "Open http://localhost:${VITE_PORT} for development."
wait
