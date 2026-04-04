# Docker Local Dev: PostgreSQL + Ollama

**Date:** 2026-03-19
**Scope:** Local development infrastructure — zero cloud dependencies for testing

---

## What Was Done

Implemented a fully local development stack using Docker images, replacing all cloud services with local equivalents. Production code is untouched; the switch is driven entirely by environment variables.

---

## Files Created

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Defines `pgvector/pgvector:pg16` and `ollama/ollama` services |
| `docker/init-db.sql` | Schema init script for local Postgres (768-dim embeddings for nomic-embed-text) |
| `backend/db/postgres_client.py` | psycopg2-backed Supabase-compatible query builder (table, insert, update, upsert, eq, in_, is_, order, limit, single, rpc, storage stub) |
| `backend/.env.local` | Ready-to-use local env config |
| `scripts/local-dev-setup.sh` | One-shot script: starts Docker, waits for health, pulls Ollama models |

## Files Modified

| File | Change |
|------|--------|
| `backend/db/supabase_client.py` | Factory: returns `PostgresClient` when `DATABASE_URL` is set, Supabase otherwise |
| `backend/services/concept_extraction.py` | Uses Ollama via OpenAI-compat API when `OLLAMA_BASE_URL` set; Anthropic otherwise |
| `backend/services/blog_generator.py` | Same Ollama/Anthropic dual-path via `_get_client()` + `_chat()` helper |
| `backend/services/embeddings.py` | Uses Ollama `nomic-embed-text` (768-dim) when `OLLAMA_BASE_URL` set; OpenAI otherwise |
| `backend/services/markdown_export.py` | Storage stub in `PostgresClient` handles `.storage.from_().upload()` locally (saves to `local_storage/`) |
| `backend/main.py` | Startup log shows which DB backend is active |
| `backend/.env.example` | Documented all new local-dev env vars |
| `backend/requirements.txt` | Added `psycopg2-binary>=2.9` |

---

## Architecture Decision: Embedding Dimensions

| Environment | Model | Dimensions |
|-------------|-------|-----------|
| Production | OpenAI `text-embedding-3-small` | 1536 |
| Local dev | Ollama `nomic-embed-text` | 768 |

The local DB schema (`docker/init-db.sql`) uses `vector(768)`. The `check_similar_videos()` function is also updated to 768-dim. Local and production data are separate environments so dimension mismatch is not an issue.

---

## How to Start Local Dev

```bash
# 1. Start stack + pull models (one-time)
./scripts/local-dev-setup.sh

# 2. Activate local config
cd backend
cp .env.local .env
pip install -r requirements.txt

# 3. Run API
uvicorn main:app --reload
```

---

## Key Design Choices

- **No PostgREST required**: `postgres_client.py` implements a Supabase-compatible query builder directly over psycopg2, covering all 8 operation types used in the codebase.
- **OpenAI SDK for Ollama**: Ollama's OpenAI-compatible API (`/v1`) lets us reuse the `openai` Python SDK for both LLM and embeddings — no new dependencies.
- **Zero production code changes**: All switching is done via `DATABASE_URL` and `OLLAMA_BASE_URL` env vars. `supabase_client.py` is the single routing point.
