#!/usr/bin/env bash
# dev.sh — One command to start the full Stream2Stack local dev stack.
#
# What it does:
#   1. Starts Docker services (Postgres + Ollama) if not already running
#   2. Waits for Postgres to be healthy
#   3. Pulls Ollama models on first run (skips if already present)
#   4. Ensures backend/.env exists
#   5. Starts FastAPI backend on :8080
#   6. Starts Next.js frontend on :3000
#   7. Ctrl+C stops everything cleanly
#
# Usage: ./dev.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}==>${NC} $*"; }
warn() { echo -e "${YELLOW}  !${NC} $*"; }

# ---------------------------------------------------------------------------
# 1. Docker services
# ---------------------------------------------------------------------------
log "Starting Docker services (Postgres + Ollama)..."
docker compose up -d

log "Waiting for Postgres to be healthy..."
until docker compose exec -T postgres pg_isready -U stream2stack -d stream2stack &>/dev/null; do
  sleep 1
done
log "Postgres ready."

log "Waiting for Ollama to be ready..."
until curl -sf http://localhost:11434/api/tags &>/dev/null; do
  sleep 2
done
log "Ollama ready."

# ---------------------------------------------------------------------------
# 2. Pull Ollama models (skip if already present)
# ---------------------------------------------------------------------------
OLLAMA_MODELS=$(curl -sf http://localhost:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(m['name'] for m in d.get('models',[])))" 2>/dev/null || echo "")

if echo "$OLLAMA_MODELS" | grep -q "llama3.2"; then
  warn "llama3.2 already present, skipping pull."
else
  log "Pulling llama3.2..."
  docker compose exec ollama ollama pull llama3.2
fi

if echo "$OLLAMA_MODELS" | grep -q "nomic-embed-text"; then
  warn "nomic-embed-text already present, skipping pull."
else
  log "Pulling nomic-embed-text..."
  docker compose exec ollama ollama pull nomic-embed-text
fi

# ---------------------------------------------------------------------------
# 3. Backend .env
# ---------------------------------------------------------------------------
if [ ! -f "$BACKEND_DIR/.env" ]; then
  if [ -f "$BACKEND_DIR/.env.local" ]; then
    warn "No backend/.env found — copying .env.local"
    cp "$BACKEND_DIR/.env.local" "$BACKEND_DIR/.env"
  else
    echo "ERROR: No backend/.env or backend/.env.local found."
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 4. Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
  echo ""
  log "Stopping backend and frontend..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  log "Done. Docker services still running — stop with: docker compose down"
}
trap cleanup INT TERM

# ---------------------------------------------------------------------------
# 5. Backend
# ---------------------------------------------------------------------------
log "Starting backend (FastAPI on :8080)..."
cd "$BACKEND_DIR"
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8080 &
BACKEND_PID=$!

# ---------------------------------------------------------------------------
# 6. Frontend
# ---------------------------------------------------------------------------
log "Starting frontend (Next.js on :3000)..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

# ---------------------------------------------------------------------------
# 7. Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}  Stream2Stack is running:${NC}"
echo "    Frontend → http://localhost:3000"
echo "    Backend  → http://localhost:8080"
echo "    API docs → http://localhost:8080/docs"
echo ""
echo "    Press Ctrl+C to stop backend + frontend."
echo "    Docker services will keep running (docker compose down to stop)."
echo ""

wait "$BACKEND_PID" "$FRONTEND_PID"
