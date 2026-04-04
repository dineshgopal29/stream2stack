# Stream2Stack

AI system that ingests YouTube playlists/videos, transcribes them, ranks by relevance, extracts concepts, generates technical blog posts, and sends email newsletters.

## Architecture

```
stream2stack/
├── frontend/     # Next.js 14 + shadcn + Tailwind
├── backend/      # FastAPI (Python 3.11+)
└── supabase/     # Migrations + schema
```

## Quick Start

### 1. Supabase Setup

1. Create a Supabase project at https://supabase.com
2. Enable the **pgvector** extension: Dashboard → Extensions → vector
3. Run `supabase/migrations/001_initial_schema.sql` in the SQL Editor
4. Create storage bucket `newsletters` (public): Dashboard → Storage → New bucket

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in all env vars in .env
uvicorn main:app --reload
```

Backend runs at http://localhost:8000. Swagger docs at http://localhost:8000/docs.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
# Set NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_URL
npm run dev
```

Frontend runs at http://localhost:3000.

## Environment Variables

### backend/.env
| Variable | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Service role key (admin access) |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key |
| `ANTHROPIC_API_KEY` | Claude API key (claude-sonnet-4-6) |
| `OPENAI_API_KEY` | OpenAI API key (text-embedding-3-small) |
| `RESEND_API_KEY` | Resend email API key |

### frontend/.env.local
| Variable | Description |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Same as backend SUPABASE_URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `NEXT_PUBLIC_API_URL` | Backend URL (default: http://localhost:8000) |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/videos/ingest` | Ingest YouTube URLs or playlist |
| GET | `/videos` | List all ingested videos |
| POST | `/newsletters/generate` | Generate newsletter from top-ranked videos |
| GET | `/newsletters?user_id=...` | List newsletters |
| GET | `/newsletters/{id}` | Get single newsletter |
| POST | `/newsletters/{id}/send` | Send newsletter via email |
| GET | `/settings/{user_id}` | Get user settings |
| PUT | `/settings/{user_id}` | Update user settings |

## Key Technical Decisions

- **Transcription**: `youtube-transcript-api` (free, no API key, Python-only — hence FastAPI backend)
- **LLM**: Claude claude-sonnet-4-6 for concept extraction + blog generation
- **Embeddings**: OpenAI `text-embedding-3-small` (1536-dim, cost-effective)
- **Ranking**: `score = (recency × 0.4) + (similarity × 0.6)` — top 5 selected
- **Deduplication**: pgvector cosine similarity check (threshold: 0.85)
- **Email**: Resend SDK with inline-styled HTML

## Phase Status

- **Phase 1** ✅ Ingestion → Transcription → Concept Extraction → Blog Generation
- **Phase 2** ✅ Embeddings → Ranking → Deduplication → Markdown Export → Email
- **Phase 3** 🚧 Supabase Auth + per-user settings + scheduled cron (partially complete)
