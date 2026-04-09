# Stream2Stack

AI system that ingests YouTube videos and website articles, transcribes/scrapes them, ranks by relevance, extracts concepts, generates technical blog posts, sends email newsletters, and automatically builds a searchable wiki knowledge base.

## Architecture

```
stream2stack/
├── frontend/     # Next.js 14 + shadcn + Tailwind
├── backend/      # FastAPI (Python 3.11+)
└── supabase/     # Migrations + schema
```

## Supported Input Types

The `/videos/ingest` endpoint accepts both YouTube URLs and website URLs in any combination:

| Type | Example | Extraction Method |
|---|---|---|
| YouTube video | `https://youtube.com/watch?v=...` | YouTube Transcript API |
| Website article | `https://venturebeat.com/...` | Firecrawl API (scrapes to Markdown) |

Mix and match freely — a single ingest call can contain multiple YouTube links and website URLs.

### Firecrawl Setup

Website scraping uses [Firecrawl](https://firecrawl.dev). Without an API key, an httpx fallback is used (may fail on JS-heavy or rate-limited sites).

```bash
# backend/.env
FIRECRAWL_API_KEY=fc-your-key-here
```

## Wiki Knowledge Base

Every ingested source (YouTube or web) automatically contributes to a wiki knowledge base at `/wiki`. After each ingest, a background compile extracts concepts, patterns, tools, and code hints from all transcripts/articles and organises them into wiki pages.

You can also trigger a manual compile:
```bash
curl -X POST http://localhost:8080/wiki/compile \
  -H "Content-Type: application/json" \
  -d '{"user_id": "system"}'
```

Wiki API endpoints:

| Method | Path | Description |
|---|---|---|
| GET | `/wiki` | List all wiki pages |
| GET | `/wiki/{slug}` | Get a single wiki page |
| GET | `/wiki/stats` | Wiki statistics (page count, word count) |
| GET | `/wiki/health` | Health check — verifies pages exist and reports issues |
| GET | `/wiki/search?q=...` | Full-text search across wiki pages |
| POST | `/wiki/compile` | Trigger a wiki rebuild |

## Quick Start (Local Dev)

### Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.com) (for local LLM inference)

### 1. Start Docker services

```bash
docker-compose up -d   # starts Postgres + pgvector
```

### 2. Apply database migrations

```bash
psql postgresql://stream2stack:password@localhost:5432/stream2stack \
  -f supabase/migrations/001_initial_schema.sql \
  -f supabase/migrations/002_wiki_schema.sql \
  -f supabase/migrations/003_web_sources.sql
```

### 3. Pull Ollama models

```bash
ollama pull llama3.2        # LLM for concept extraction + generation
ollama pull nomic-embed-text  # embeddings
```

### 4. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in env vars (see below)
uvicorn main:app --reload --port 8080
```

### 5. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at http://localhost:3000. API at http://localhost:8080/docs.

## Environment Variables

### backend/.env

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Local dev | `postgresql://stream2stack:password@localhost:5432/stream2stack` |
| `YOUTUBE_API_KEY` | Yes | YouTube Data API v3 key |
| `OLLAMA_BASE_URL` | Local dev | `http://localhost:11434` |
| `OLLAMA_LLM_MODEL` | Local dev | `llama3.2` |
| `OLLAMA_EMBED_MODEL` | Local dev | `nomic-embed-text` |
| `ANTHROPIC_API_KEY` | Production | Claude API key (claude-sonnet-4-6) |
| `OPENAI_API_KEY` | Production | OpenAI embeddings key |
| `FIRECRAWL_API_KEY` | Optional | Firecrawl key for website scraping |
| `RESEND_API_KEY` | Email | Resend email API key |
| `SUPABASE_URL` | Production | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Production | Supabase service role key |

### frontend/.env.local

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL (default: `http://localhost:8080`) |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/videos/ingest` | Ingest YouTube URLs and/or website URLs |
| GET | `/videos` | List all ingested sources |
| POST | `/newsletters/generate` | Generate newsletter from top-ranked sources |
| GET | `/newsletters?user_id=...` | List newsletters |
| GET | `/newsletters/{id}` | Get single newsletter |
| POST | `/newsletters/{id}/send` | Send newsletter via email |
| GET | `/wiki` | List wiki pages |
| GET | `/wiki/{slug}` | Get wiki page |
| GET | `/wiki/stats` | Wiki statistics |
| GET | `/wiki/health` | Wiki health check |
| GET | `/wiki/search?q=...` | Search wiki |
| POST | `/wiki/compile` | Rebuild wiki |
| DELETE | `/admin/data` | Clear all data (dev/test only) |

## Running E2E Tests

```bash
# Requires backend (port 8080) and frontend (port 3000) to be running
cd frontend
npx playwright test

# Note: The beforeAll fixture ingests sources and generates a newsletter.
# With local Ollama this can take 10–20 minutes on first run.
```

## Key Technical Decisions

- **YouTube transcription**: `youtube-transcript-api` (free, no API key)
- **Website scraping**: Firecrawl API → clean Markdown; httpx fallback for simple sites
- **LLM (local)**: Ollama with llama3.2 for concept extraction + generation
- **LLM (production)**: Claude claude-sonnet-4-6
- **Embeddings (local)**: Ollama `nomic-embed-text` (768-dim)
- **Embeddings (production)**: OpenAI `text-embedding-3-small` (1536-dim)
- **Ranking**: `score = (recency × 0.4) + (similarity × 0.6)` — top 5 selected
- **Deduplication**: pgvector cosine similarity check (threshold: 0.85)
- **Wiki compile**: background task triggered after every ingest; also supports manual trigger
- **Email**: Resend SDK with inline-styled HTML

## Phase Status

- **Phase 1** ✅ Ingestion → Transcription → Concept Extraction → Blog Generation
- **Phase 2** ✅ Embeddings → Ranking → Deduplication → Markdown Export → Email
- **Phase 3** ✅ Wiki Knowledge Base — auto-compiled from all ingested sources
- **Phase 4** ✅ Multi-source ingestion — YouTube + website URLs in the same request
- **Phase 5** 🚧 Supabase Auth + per-user settings + scheduled cron (partially complete)
