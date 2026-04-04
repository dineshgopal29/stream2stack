#!/usr/bin/env bash
# start-dev.sh — Start backend (FastAPI) and frontend (Next.js) for local development.
# Run from the project root: ./scripts/start-dev.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

# Ensure .env exists for backend
if [ ! -f "$BACKEND_DIR/.env" ]; then
  if [ -f "$BACKEND_DIR/.env.local" ]; then
    echo "==> No backend/.env found — copying .env.local"
    cp "$BACKEND_DIR/.env.local" "$BACKEND_DIR/.env"
  else
    echo "ERROR: No backend/.env or backend/.env.local found. Create one before starting."
    exit 1
  fi
fi

cleanup() {
  echo ""
  echo "==> Stopping services..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "==> Done."
}
trap cleanup INT TERM

# --- Backend ---
echo "==> Starting backend (FastAPI on :8080)..."
cd "$BACKEND_DIR"
uvicorn main:app --reload --host 0.0.0.0 --port 8080 &
BACKEND_PID=$!

# --- Frontend ---
echo "==> Starting frontend (Next.js on :3000)..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "==> Services running:"
echo "    Backend  → http://localhost:8080"
echo "    Frontend → http://localhost:3000"
echo "    API docs → http://localhost:8080/docs"
echo ""
echo "    Press Ctrl+C to stop both."

wait "$BACKEND_PID" "$FRONTEND_PID"
