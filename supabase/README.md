# Supabase Setup — Stream2Stack

This directory contains the SQL migration(s) needed to bootstrap the Stream2Stack
database on Supabase.

---

## 1. Enable pgvector

pgvector ships as a first-party Supabase extension; it just needs to be turned on.

**Option A — Supabase Dashboard**

1. Open your project in the [Supabase dashboard](https://app.supabase.com).
2. Navigate to **Database → Extensions**.
3. Search for **vector** and toggle it on.

**Option B — SQL editor / migration file**

The first line of `migrations/001_initial_schema.sql` already handles this:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Running the migration file (see section 2) is sufficient.

---

## 2. Run the Migration

### Option A — Supabase SQL Editor (quickest for development)

1. Open the [Supabase dashboard](https://app.supabase.com) and select your project.
2. Go to **SQL Editor → New query**.
3. Copy and paste the full contents of `migrations/001_initial_schema.sql`.
4. Click **Run**.

### Option B — Supabase CLI

Install the CLI if you haven't already:

```bash
npm install -g supabase
# or
brew install supabase/tap/supabase
```

Link your project and push migrations:

```bash
# From the repo root
supabase login
supabase link --project-ref <your-project-ref>
supabase db push
```

`<your-project-ref>` is the string in your project URL:
`https://app.supabase.com/project/<your-project-ref>`

### Option C — psql direct connection

```bash
psql "postgresql://postgres:<db-password>@db.<your-project-ref>.supabase.co:5432/postgres" \
  -f supabase/migrations/001_initial_schema.sql
```

---

## 3. Set Up the Storage Bucket

The `newsletters` bucket stores generated Markdown files for each newsletter.

### Option A — Supabase Dashboard

1. Go to **Storage** in the left sidebar.
2. Click **New bucket**.
3. Name it `newsletters`.
4. Check **Public bucket** if you want direct URL access to the files (recommended
   for demo usage).
5. Click **Create bucket**.

### Option B — SQL (after the migration has run)

Run the following in the SQL editor:

```sql
INSERT INTO storage.buckets (id, name, public)
VALUES ('newsletters', 'newsletters', true)
ON CONFLICT DO NOTHING;
```

This line is also present (commented out) at the bottom of the migration file for
reference.

---

## 4. Environment Variables

All Supabase credentials are consumed by the backend. Copy the example file and
fill in your values:

```bash
cp backend/.env.example backend/.env
```

See [`backend/.env.example`](../backend/.env.example) for the full list. The
Supabase-specific variables you must set are:

| Variable | Where to find it |
|---|---|
| `SUPABASE_URL` | Dashboard → Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | Dashboard → Settings → API → `anon` / `public` key |
| `SUPABASE_SERVICE_KEY` | Dashboard → Settings → API → `service_role` key (keep secret) |

> **Never commit `backend/.env` to version control.** It is already listed in
> `.gitignore`.

---

## 5. Schema Overview

| Table | Purpose |
|---|---|
| `videos` | Stores YouTube video metadata, transcripts, and OpenAI embeddings |
| `newsletters` | Generated newsletter drafts and sent records |
| `newsletter_videos` | Junction table linking newsletters to their source videos |
| `processed_videos` | Tracks which videos a user has already seen / processed |
| `user_settings` | Per-user preferences (frequency, topics, playlist URLs, recipient email) |

### Notable design decisions

- **pgvector (`embedding vector(1536)`)** — stores OpenAI `text-embedding-3-small`
  embeddings on each video so that near-duplicate content can be detected with
  cosine similarity before including a video in a newsletter.
- **`check_similar_videos` RPC** — callable from the backend via
  `supabase.rpc('check_similar_videos', {...})`. Returns videos whose cosine
  similarity to a given embedding exceeds the threshold (default 0.85).
- **IVFFlat index** — `idx_videos_embedding` accelerates approximate nearest-
  neighbour search. The `lists = 100` setting is appropriate for up to ~1 million
  rows; tune upward if the dataset grows significantly.
- **`user_id` as `text`** — both `processed_videos` and `user_settings` use a plain
  `text` primary key so the app works without Supabase Auth during the demo phase.
  Migrate to `uuid` referencing `auth.users` when auth is added.
