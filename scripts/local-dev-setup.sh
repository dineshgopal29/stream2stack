#!/usr/bin/env bash
# local-dev-setup.sh — Start local dev stack and pull required Ollama models.
# Run from the project root: ./scripts/local-dev-setup.sh

set -euo pipefail

echo "==> Starting Docker services..."
docker compose up -d

echo "==> Waiting for Postgres to be healthy..."
until docker compose exec -T postgres pg_isready -U stream2stack -d stream2stack &>/dev/null; do
  sleep 1
done
echo "    Postgres ready."

echo "==> Waiting for Ollama to be ready..."
until curl -sf http://localhost:11434/api/tags &>/dev/null; do
  sleep 2
done
echo "    Ollama ready."

echo "==> Pulling LLM model (llama3.2)..."
docker compose exec ollama ollama pull llama3.2

echo "==> Pulling embedding model (nomic-embed-text)..."
docker compose exec ollama ollama pull nomic-embed-text

echo ""
echo "==> Local dev stack is ready!"
echo ""
echo "    Next steps:"
echo "    1. cd backend"
echo "    2. cp .env.local .env"
echo "    3. pip install -r requirements.txt"
echo "    4. uvicorn main:app --reload"
