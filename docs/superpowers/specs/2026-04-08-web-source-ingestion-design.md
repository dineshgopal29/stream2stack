# Web Source Ingestion — Design Spec

**Status:** Approved  
**Date:** 2026-04-08  
**Author:** Dinesh Gopal

---

## Goal

Extend Stream2Stack so the "Video URLs" tab accepts both YouTube URLs and arbitrary website URLs in the same textarea. Web articles are scraped via Firecrawl, stored alongside YouTube videos in the DB, and flow through the same concept-extraction → wiki-compiler pipeline. After every ingest, the wiki is compiled automatically.

---

## Scope

1. DB migration — add `source_type` and `source_url` columns to `videos`
2. Backend — new `web_ingestion.py` service; modify `/videos/ingest` route to detect URL type; auto-trigger wiki compile; add `DELETE /admin/data` clear endpoint
3. Frontend — update "Video URLs" tab description + placeholder; add Globe icon fallback for web sources
4. Playwright E2E tests — full ingest → newsletter → wiki flow with the provided test URLs
5. README update

---

## Architecture

```
User submits URLs (YouTube + web mixed)
        │
        ▼
POST /videos/ingest
        │
        ├─ YouTube URL ──► youtube_ingestion.py ──► videos table (source_type='youtube')
        │                                           │
        └─ Web URL ──────► web_ingestion.py ───────► videos table (source_type='web')
                           (Firecrawl scrape)        source_url = original URL
                                                     youtube_id = md5(url)[:11]
                                                     transcript = scraped markdown
                                                     │
                                                     ▼
                                         concept_extraction.py  (unchanged)
                                                     │
                                                     ▼
                                         wiki_compiler.py  (unchanged)
                                         [auto-triggered after ingest]
```

---

## Data Layer

### Migration 003 (`supabase/migrations/003_web_sources.sql`)

```sql
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'youtube';
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_url text;
COMMENT ON COLUMN videos.source_type IS 'youtube | web';
COMMENT ON COLUMN videos.source_url  IS 'Original URL for web-scraped sources';
```

### Web source record shape

| Field | Value |
|-------|-------|
| `youtube_id` | `md5(url.encode()).hexdigest()[:11]` — deterministic, satisfies UNIQUE NOT NULL |
| `source_type` | `'web'` |
| `source_url` | original URL |
| `title` | first `# heading` in scraped markdown, or URL hostname as fallback |
| `description` | first paragraph of scraped markdown (≤ 300 chars) |
| `channel_name` | hostname (e.g. `venturebeat.com`) |
| `transcript` | full scraped markdown (truncated to 24 000 chars by Firecrawl service) |
| `thumbnail_url` | `''` (empty — frontend shows Globe icon) |
| `duration_seconds` | `0` |
| `published_at` | `None` |

---

## Backend Changes

### New: `backend/services/web_ingestion.py`

```python
def ingest_web_url(url: str) -> dict:
    """Scrape a web URL and upsert into the videos table as source_type='web'."""
```

- Calls `firecrawl_crawler.crawl_url(url)` — already handles Firecrawl + httpx fallback
- Extracts title: first `# ` heading in markdown, fallback to `urlparse(url).hostname`
- Extracts description: first non-heading paragraph ≤ 300 chars
- `youtube_id = hashlib.md5(url.encode()).hexdigest()[:11]`
- Upserts into `videos` with `source_type='web'`, `source_url=url`
- Returns same dict shape as `youtube_ingestion.ingest_videos` records

### Modified: `backend/api/routes/videos.py`

`POST /videos/ingest` — for each URL in `body.urls`:
- If `is_youtube_url(url)` → existing YouTube path
- Else → `web_ingestion.ingest_web_url(url)`

Both paths produce a `video` dict; existing transcript+embedding+processing pipeline runs unchanged.

After all videos processed: fire `asyncio.create_task(compile_wiki_background())` — non-blocking.

### New: `DELETE /admin/data` (in `backend/api/routes/admin.py`)

Truncates: `videos`, `newsletters`, `newsletter_videos`, `processed_videos`.  
Also deletes `local_storage/wiki/` directory.  
Returns `{"cleared": true}`.

### URL type detection helper

```python
def is_youtube_url(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    return "youtube.com" in host or "youtu.be" in host
```

---

## Frontend Changes

### `frontend/app/input/page.tsx`

- Tab description: `"Enter YouTube video URLs or website links — one per line. Mix and match freely."`
- Textarea placeholder:
  ```
  https://youtube.com/watch?v=abc123
  https://venturebeat.com/data/karpathy-llm-architecture
  ```
- `VideoCard`: when `video.thumbnail_url` is falsy, show `Globe` icon (import from lucide-react) instead of `Youtube` icon

### `frontend/lib/api.ts`

No functional changes — `ingestVideos` already sends `urls[]` as-is.

---

## Playwright E2E Tests

### File: `frontend/tests/e2e/ingest-and-wiki.spec.ts`

**Test URLs:**
- `https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an`
- `https://www.youtube.com/watch?v=kwSVtQ7dziU`

**Setup:** `beforeAll` calls `DELETE http://localhost:8080/admin/data` to clear state.

**Test 1 — Ingest mixed URLs:**
1. Navigate to `http://localhost:3000/input`
2. Find textarea, enter both URLs (one per line)
3. Click "Ingest Videos"
4. Wait for success card: "2 Sources Ingested" (or "2 Videos Ingested")
5. Assert card is visible

**Test 2 — Generate newsletter:**
1. (Continues from Test 1) Click "Generate Newsletter"
2. Wait for "Newsletter Created!" card
3. Assert "View Newsletter" link is visible

**Test 3 — Wiki pages created:**
1. Navigate to `http://localhost:3000/wiki`
2. Assert at least one wiki page card is visible (after auto-compile)

**Test 4 — Wiki health endpoint:**
1. `GET http://localhost:8080/wiki/health`
2. Assert `pages_checked > 0`

---

## Admin Clear Data

`DELETE /admin/data`:
- Executes `DELETE FROM videos`, `DELETE FROM newsletters`, `DELETE FROM newsletter_videos`, `DELETE FROM processed_videos` (in correct FK order)
- Removes `local_storage/wiki/` directory (shutil.rmtree)
- Returns `{"cleared": true, "tables": ["videos", "newsletters", "newsletter_videos", "processed_videos"]}`

---

## Test URLs

| URL | Type | Expected outcome |
|-----|------|-----------------|
| `https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an` | Web | Scraped via Firecrawl, concepts extracted, wiki page created |
| `https://www.youtube.com/watch?v=kwSVtQ7dziU` | YouTube | Transcript fetched, concepts extracted, wiki page created |

---

## README Changes

Add section "Supported Input Types" explaining YouTube URLs + website URLs, Firecrawl setup, and the wiki knowledge base.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-08 | Initial spec — web source ingestion, Playwright E2E, wiki auto-compile |
