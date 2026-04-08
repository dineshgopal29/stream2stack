# Web Source Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the ingest pipeline so the "Video URLs" textarea accepts YouTube URLs and website URLs interchangeably — web articles are scraped via Firecrawl, stored in the `videos` table, and flow through concept-extraction → wiki-compiler automatically.

**Architecture:** Add `source_type` and `source_url` columns to `videos` via a DB migration. A new `web_ingestion.py` service scrapes URLs using the existing `firecrawl_crawler.py`, then upserts into `videos` using `md5(url)[:11]` as the `youtube_id`. The `/videos/ingest` route detects URL type and routes to either YouTube or web ingestion, then fires a non-blocking background wiki compile. An `admin.py` route clears all data for testing. Playwright E2E tests verify the full flow with the two provided test URLs.

**Tech Stack:** Python 3.11, FastAPI, firecrawl-py 1.15.0 (already installed), PostgreSQL, Next.js 14, Playwright (new dev dependency), pytest.

---

## File Map

| File | Change |
|------|--------|
| `supabase/migrations/003_web_sources.sql` | **New** — adds `source_type`, `source_url` columns |
| `backend/services/web_ingestion.py` | **New** — scrape URL, upsert to `videos` |
| `backend/tests/unit/test_web_ingestion.py` | **New** — unit tests for web_ingestion |
| `backend/api/routes/admin.py` | **New** — `DELETE /admin/data` |
| `backend/api/routes/videos.py` | **Modify** — detect URL type, route web URLs, auto-trigger wiki compile |
| `backend/main.py` | **Modify** — register admin router |
| `frontend/app/input/page.tsx` | **Modify** — update tab description, placeholder, Globe icon |
| `frontend/playwright.config.ts` | **New** — Playwright configuration |
| `frontend/tests/e2e/ingest-and-wiki.spec.ts` | **New** — E2E test suite |
| `frontend/package.json` | **Modify** — add `@playwright/test` dev dependency |
| `README.md` | **Modify** — add Supported Input Types section |

---

## Task 1: DB Migration

**Files:**
- Create: `supabase/migrations/003_web_sources.sql`

- [ ] **Step 1.1: Create the migration file**

```sql
-- supabase/migrations/003_web_sources.sql
-- Add source_type and source_url columns to the videos table.
-- source_type: 'youtube' (default) or 'web'
-- source_url:  original URL for web-scraped sources (null for YouTube videos)

ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'youtube';
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_url text;

COMMENT ON COLUMN videos.source_type IS 'youtube | web';
COMMENT ON COLUMN videos.source_url  IS 'Original URL for web-scraped sources (null for YouTube)';
```

- [ ] **Step 1.2: Apply the migration**

```bash
# Apply to local Docker Postgres
docker exec -i stream2stack-postgres-1 psql -U stream2stack -d stream2stack < /Users/dinesh/Documents/My_Product/stream2stack/supabase/migrations/003_web_sources.sql
```

Expected output:
```
ALTER TABLE
ALTER TABLE
COMMENT
COMMENT
```

- [ ] **Step 1.3: Verify columns exist**

```bash
docker exec stream2stack-postgres-1 psql -U stream2stack -d stream2stack -c "\d videos"
```

Expected: `source_type` and `source_url` columns appear in the table description.

- [ ] **Step 1.4: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
git add supabase/migrations/003_web_sources.sql
git commit -m "feat: add source_type and source_url columns to videos table"
```

---

## Task 2: web_ingestion.py Service

**Files:**
- Create: `backend/services/web_ingestion.py`
- Create: `backend/tests/unit/test_web_ingestion.py`

- [ ] **Step 2.1: Write failing tests**

Create `backend/tests/unit/test_web_ingestion.py`:

```python
"""Unit tests for services/web_ingestion.py."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from services.web_ingestion import (
    _url_to_id,
    _extract_title,
    _extract_description,
    ingest_web_url,
)


# ---------------------------------------------------------------------------
# _url_to_id
# ---------------------------------------------------------------------------

def test_url_to_id_is_11_chars():
    uid = _url_to_id("https://example.com/article")
    assert len(uid) == 11


def test_url_to_id_is_deterministic():
    url = "https://venturebeat.com/data/some-article"
    assert _url_to_id(url) == _url_to_id(url)


def test_url_to_id_differs_for_different_urls():
    assert _url_to_id("https://a.com") != _url_to_id("https://b.com")


def test_url_to_id_alphanumeric():
    uid = _url_to_id("https://example.com/foo?bar=1")
    assert uid.isalnum(), f"Expected alphanumeric, got: {uid!r}"


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------

def test_extract_title_from_h1():
    md = "# My Article Title\n\nSome content here."
    assert _extract_title(md, "https://example.com") == "My Article Title"


def test_extract_title_fallback_to_hostname():
    md = "Just some text without a heading."
    assert _extract_title(md, "https://venturebeat.com/article") == "venturebeat.com"


def test_extract_title_strips_whitespace():
    md = "#   Padded Title  \n\nContent."
    assert _extract_title(md, "https://example.com") == "Padded Title"


# ---------------------------------------------------------------------------
# _extract_description
# ---------------------------------------------------------------------------

def test_extract_description_first_paragraph():
    md = "# Title\n\nThis is the first paragraph. It has two sentences.\n\n## Section\n\nMore."
    desc = _extract_description(md)
    assert desc == "This is the first paragraph. It has two sentences."


def test_extract_description_truncates_at_300():
    md = "# Title\n\n" + "x" * 400
    assert len(_extract_description(md)) <= 300


def test_extract_description_empty_on_no_content():
    md = "# Title\n\n## Section only"
    assert _extract_description(md) == ""


# ---------------------------------------------------------------------------
# ingest_web_url (integration — mocked DB + Firecrawl)
# ---------------------------------------------------------------------------

def test_ingest_web_url_returns_video_dict():
    mock_markdown = "# Karpathy LLM Architecture\n\nThis article explains how LLMs work."

    mock_upsert = MagicMock()
    mock_upsert.execute.return_value = MagicMock(
        data=[{
            "id": "uuid-123",
            "youtube_id": "abc12345678",
            "title": "Karpathy LLM Architecture",
            "source_type": "web",
            "source_url": "https://example.com/article",
        }]
    )

    mock_table = MagicMock()
    mock_table.upsert.return_value = mock_upsert

    mock_supabase = MagicMock()
    mock_supabase.table.return_value = mock_table

    with patch("services.web_ingestion.crawl_url", return_value=mock_markdown), \
         patch("services.web_ingestion.get_supabase_client", return_value=mock_supabase):
        result = ingest_web_url("https://example.com/article")

    assert result["id"] == "uuid-123"
    assert result["source_type"] == "web"


def test_ingest_web_url_raises_on_crawl_failure():
    with patch("services.web_ingestion.crawl_url", return_value=None):
        with pytest.raises(ValueError, match="Failed to scrape"):
            ingest_web_url("https://example.com/article")
```

- [ ] **Step 2.2: Run tests — verify they fail**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python3 -m pytest tests/unit/test_web_ingestion.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'services.web_ingestion'`

- [ ] **Step 2.3: Create `backend/services/web_ingestion.py`**

```python
"""
Web article ingestion service.

Scrapes a URL via Firecrawl (with httpx fallback), extracts metadata,
and upserts into the videos table as source_type='web'.

The youtube_id field is set to md5(url)[:11] — a deterministic 11-char
identifier that satisfies the UNIQUE NOT NULL constraint without requiring
a schema change to that column.

Public API:
    ingest_web_url(url: str) -> dict
"""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse

from db.supabase_client import get_supabase_client
from services.firecrawl_crawler import crawl_url

logger = logging.getLogger(__name__)

_H1_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _url_to_id(url: str) -> str:
    """Return a deterministic 11-char alphanumeric identifier for a URL."""
    return hashlib.md5(url.encode()).hexdigest()[:11]


def _extract_title(markdown: str, url: str) -> str:
    """Return first # heading, falling back to hostname."""
    m = _H1_RE.search(markdown)
    if m:
        return m.group(1).strip()
    return urlparse(url).hostname or url


def _extract_description(markdown: str) -> str:
    """Return the first non-heading paragraph, truncated to 300 chars."""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:300]
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_web_url(url: str) -> dict:
    """Scrape a URL and upsert it into the videos table as source_type='web'.

    Args:
        url: HTTP/HTTPS URL to scrape.

    Returns:
        The upserted video record dict (contains 'id', 'youtube_id', etc.).

    Raises:
        ValueError: If Firecrawl returns no content.
    """
    markdown = crawl_url(url)
    if not markdown:
        raise ValueError(f"Failed to scrape URL: {url!r}")

    title = _extract_title(markdown, url)
    description = _extract_description(markdown)
    hostname = urlparse(url).hostname or ""
    uid = _url_to_id(url)

    record = {
        "youtube_id": uid,
        "source_type": "web",
        "source_url": url,
        "title": title,
        "description": description,
        "channel_name": hostname,
        "transcript": markdown,
        "thumbnail_url": "",
        "duration_seconds": 0,
        "published_at": None,
    }

    supabase = get_supabase_client()
    result = (
        supabase.table("videos")
        .upsert(record, on_conflict="youtube_id")
        .execute()
    )

    records = result.data
    if records:
        logger.info("Upserted web source %r → DB id=%s", url, records[0].get("id"))
        return records[0]

    # Row already existed — fetch it
    existing = (
        supabase.table("videos")
        .select("*")
        .eq("youtube_id", uid)
        .single()
        .execute()
    )
    if existing.data:
        return existing.data

    raise RuntimeError(f"Upsert produced no record for {url!r}")
```

- [ ] **Step 2.4: Run tests — verify they pass**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python3 -m pytest tests/unit/test_web_ingestion.py -v
```

Expected: 11 tests pass.

- [ ] **Step 2.5: Run full unit suite — no regressions**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python3 -m pytest tests/unit/ -v 2>&1 | tail -5
```

Expected: 130 tests pass (119 existing + 11 new).

- [ ] **Step 2.6: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
git add backend/services/web_ingestion.py backend/tests/unit/test_web_ingestion.py
git commit -m "feat: add web_ingestion service — scrape URLs via Firecrawl and store in videos table"
```

---

## Task 3: Admin Clear-Data Endpoint

**Files:**
- Create: `backend/api/routes/admin.py`
- Modify: `backend/main.py` (lines 8, 94)

- [ ] **Step 3.1: Create `backend/api/routes/admin.py`**

```python
"""
Admin utility routes.

DELETE /admin/data — clear all ingested data and wiki pages.
Intended for development/testing only. Not rate-limited.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from db.supabase_client import get_supabase_client

router = APIRouter()
logger = logging.getLogger(__name__)

# Tables cleared in FK-safe order (children before parents)
_TABLES = ["newsletter_videos", "processed_videos", "newsletters", "videos"]

# Wiki filesystem root (same constant used by wiki_store.py)
_WIKI_ROOT = Path(__file__).resolve().parents[2] / "local_storage" / "wiki"


@router.delete(
    "/data",
    status_code=status.HTTP_200_OK,
    summary="Clear all ingested data",
    description=(
        "Deletes all rows from videos, newsletters, newsletter_videos, and "
        "processed_videos tables. Also removes the local_storage/wiki/ directory. "
        "For development and testing only."
    ),
)
async def clear_data() -> dict:
    supabase = get_supabase_client()

    cleared_tables: list[str] = []
    for table in _TABLES:
        try:
            # Supabase requires a filter for DELETE — use neq on id with empty string
            # to match all rows. For tables without 'id', use a truthy filter.
            if table in ("newsletter_videos",):
                supabase.table(table).delete().neq("newsletter_id", "").execute()
            elif table in ("processed_videos",):
                supabase.table(table).delete().neq("user_id", "").execute()
            else:
                supabase.table(table).delete().neq("id", "").execute()
            cleared_tables.append(table)
            logger.info("Cleared table: %s", table)
        except Exception as exc:
            logger.warning("Failed to clear table %s: %s", table, exc)

    # Remove wiki filesystem
    if _WIKI_ROOT.exists():
        shutil.rmtree(_WIKI_ROOT)
        logger.info("Removed wiki directory: %s", _WIKI_ROOT)

    return {"cleared": True, "tables": cleared_tables}
```

- [ ] **Step 3.2: Register admin router in `backend/main.py`**

Change line 8 from:
```python
from api.routes import videos, newsletters, settings, usage, cron, license as license_routes, wiki as wiki_routes
```
to:
```python
from api.routes import videos, newsletters, settings, usage, cron, license as license_routes, wiki as wiki_routes, admin as admin_routes
```

After line 94 (`app.include_router(wiki_routes.router, ...)`), add:
```python
    app.include_router(admin_routes.router,    prefix="/admin",     tags=["Admin"])
```

- [ ] **Step 3.3: Verify endpoint loads**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python3 -c "from api.routes.admin import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3.4: Verify endpoint appears in OpenAPI**

Start backend if not running:
```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
uvicorn main:app --host 0.0.0.0 --port 8080 --reload &
sleep 2
curl -s http://localhost:8080/openapi.json | python3 -c "import json,sys; paths=json.load(sys.stdin)['paths']; print([p for p in paths if 'admin' in p])"
```

Expected: `['/admin/data']`

- [ ] **Step 3.5: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
git add backend/api/routes/admin.py backend/main.py
git commit -m "feat: add DELETE /admin/data endpoint to clear all ingested data and wiki"
```

---

## Task 4: Modify /videos/ingest for Mixed URLs + Auto-Wiki-Compile

**Files:**
- Modify: `backend/api/routes/videos.py`

Current file is at `backend/api/routes/videos.py`. The ingest route is at line 45.

- [ ] **Step 4.1: Read the current file to confirm line numbers**

```bash
grep -n "def ingest_videos\|from services\|is_youtube" /Users/dinesh/Documents/My_Product/stream2stack/backend/api/routes/videos.py
```

- [ ] **Step 4.2: Add web_ingestion import and URL-type helper**

At the top of `backend/api/routes/videos.py`, change the imports block from:
```python
from services import (
    embeddings as embeddings_svc,
    transcription as transcription_svc,
    youtube_ingestion as ingestion_svc,
)
from services.quota_gate import QuotaGate
```
to:
```python
from services import (
    embeddings as embeddings_svc,
    transcription as transcription_svc,
    youtube_ingestion as ingestion_svc,
    web_ingestion as web_svc,
)
from services import wiki_compiler as compiler_svc
from services.quota_gate import QuotaGate
from urllib.parse import urlparse


def _is_youtube_url(url: str) -> bool:
    """Return True if url points to YouTube (youtube.com or youtu.be)."""
    host = urlparse(url.strip()).hostname or ""
    return "youtube.com" in host or "youtu.be" in host
```

- [ ] **Step 4.3: Replace the ingestion logic inside `ingest_videos`**

In `backend/api/routes/videos.py`, find the block after the quota check (around line 65):
```python
    # Step 1: Ingest metadata (sync operation wrapped in thread pool).
    try:
        videos: list[dict[str, Any]] = await asyncio.to_thread(
            ingestion_svc.ingest_videos,
            body.urls,
            body.playlist_url,
        )
    except Exception as exc:
        logger.exception("Video ingestion failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YouTube API error during ingestion: {exc}",
        )

    if not videos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid videos could be ingested from the provided URLs.",
        )
```

Replace it with:
```python
    # Step 1: Split URLs into YouTube vs web, then ingest both types.
    youtube_urls = [u for u in body.urls if _is_youtube_url(u)]
    web_urls     = [u for u in body.urls if not _is_youtube_url(u)]

    videos: list[dict[str, Any]] = []

    # YouTube ingestion
    if youtube_urls or body.playlist_url:
        try:
            yt_videos = await asyncio.to_thread(
                ingestion_svc.ingest_videos,
                youtube_urls,
                body.playlist_url,
            )
            videos.extend(yt_videos)
        except Exception as exc:
            logger.exception("YouTube ingestion failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"YouTube API error during ingestion: {exc}",
            )

    # Web ingestion
    for url in web_urls:
        try:
            web_video = await asyncio.to_thread(web_svc.ingest_web_url, url)
            videos.append(web_video)
        except Exception as exc:
            logger.warning("Web ingestion failed for %r: %s", url, exc)

    if not videos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid sources could be ingested from the provided URLs.",
        )
```

- [ ] **Step 4.4: Add auto-wiki-compile at the end of `ingest_videos`**

Find the return statement at the end of `ingest_videos`:
```python
    return VideoIngestResponse(
        videos=processed,
        message=f"Successfully ingested {len(processed)} video(s).",
    )
```

Replace with:
```python
    # Fire-and-forget wiki compile so knowledge base stays fresh.
    async def _compile_wiki_bg() -> None:
        try:
            await asyncio.to_thread(compiler_svc.compile_wiki, user_id="system")
            logger.info("Background wiki compile completed after ingest.")
        except Exception as exc:
            logger.warning("Background wiki compile failed: %s", exc)

    asyncio.create_task(_compile_wiki_bg())

    return VideoIngestResponse(
        videos=processed,
        message=f"Successfully ingested {len(processed)} source(s).",
    )
```

- [ ] **Step 4.5: Verify the module imports cleanly**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python3 -c "from api.routes.videos import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4.6: Run unit tests — no regressions**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python3 -m pytest tests/unit/ -v 2>&1 | tail -5
```

Expected: all 130 tests pass.

- [ ] **Step 4.7: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
git add backend/api/routes/videos.py
git commit -m "feat: route mixed YouTube+web URLs in /videos/ingest, auto-trigger wiki compile"
```

---

## Task 5: Frontend Input Page Updates

**Files:**
- Modify: `frontend/app/input/page.tsx`

- [ ] **Step 5.1: Update the "Video URLs" tab description and placeholder**

In `frontend/app/input/page.tsx`, find:
```tsx
              <CardDescription>
                Enter YouTube video URLs or a playlist URL to ingest.
              </CardDescription>
```
Replace with:
```tsx
              <CardDescription>
                Enter YouTube video URLs or website links — one per line. Mix and match freely.
              </CardDescription>
```

Find the `<Label>` and `<Textarea>` in the Video URLs tab:
```tsx
                <Label htmlFor="video-urls">YouTube Video URLs</Label>
                <Textarea
                  id="video-urls"
                  placeholder={`https://youtube.com/watch?v=abc123\nhttps://youtube.com/watch?v=def456\nhttps://youtube.com/watch?v=ghi789`}
```
Replace with:
```tsx
                <Label htmlFor="video-urls">YouTube or Website URLs</Label>
                <Textarea
                  id="video-urls"
                  placeholder={`https://youtube.com/watch?v=abc123\nhttps://venturebeat.com/data/karpathy-llm-architecture`}
```

Find the helper text below the textarea:
```tsx
                <p className="text-xs text-muted-foreground">
                  One URL per line. Supports youtube.com/watch and youtu.be
                  links.
                </p>
```
Replace with:
```tsx
                <p className="text-xs text-muted-foreground">
                  One URL per line. Supports YouTube links and any https:// website URL.
                </p>
```

- [ ] **Step 5.2: Add Globe icon fallback for web sources in VideoCard**

In `frontend/app/input/page.tsx`, find the import line:
```tsx
import {
  Loader2,
  Youtube,
  ListVideo,
  CheckCircle2,
  ArrowRight,
  Mail,
  Sparkles,
  Plus,
  X,
  Link as LinkIcon,
} from "lucide-react"
```
Add `Globe` to the import:
```tsx
import {
  Loader2,
  Youtube,
  ListVideo,
  CheckCircle2,
  ArrowRight,
  Mail,
  Sparkles,
  Plus,
  X,
  Link as LinkIcon,
  Globe,
} from "lucide-react"
```

In the `VideoCard` component, find the fallback for missing thumbnail:
```tsx
        <div className="h-16 w-28 flex-shrink-0 rounded bg-muted flex items-center justify-center">
          <Youtube className="h-6 w-6 text-muted-foreground" />
        </div>
```
Replace with:
```tsx
        <div className="h-16 w-28 flex-shrink-0 rounded bg-muted flex items-center justify-center">
          {(video as any).source_type === "web" ? (
            <Globe className="h-6 w-6 text-muted-foreground" />
          ) : (
            <Youtube className="h-6 w-6 text-muted-foreground" />
          )}
        </div>
```

- [ ] **Step 5.3: Verify frontend build passes**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npm run build 2>&1 | tail -10
```

Expected: build succeeds with no type errors.

- [ ] **Step 5.4: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
git add frontend/app/input/page.tsx
git commit -m "feat: update Video URLs tab to accept website URLs alongside YouTube links"
```

---

## Task 6: Playwright E2E Tests

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/tests/e2e/ingest-and-wiki.spec.ts`

- [ ] **Step 6.1: Install Playwright**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npm install --save-dev @playwright/test
npx playwright install chromium
```

Expected: Playwright installed, Chromium browser downloaded.

- [ ] **Step 6.2: Create `frontend/playwright.config.ts`**

```typescript
import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,        // 2 min per test — LLM calls are slow
  retries: 0,
  workers: 1,              // sequential — tests share backend state
  use: {
    baseURL: "http://localhost:3000",
    headless: true,
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
})
```

- [ ] **Step 6.3: Create `frontend/tests/e2e/ingest-and-wiki.spec.ts`**

```typescript
import { test, expect, request } from "@playwright/test"

const BACKEND = "http://localhost:8080"
const VENTUREBEAT_URL =
  "https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an"
const YOUTUBE_URL = "https://www.youtube.com/watch?v=kwSVtQ7dziU"

// Clear all data before running the suite
test.beforeAll(async () => {
  const ctx = await request.newContext()
  const res = await ctx.delete(`${BACKEND}/admin/data`)
  expect(res.status()).toBe(200)
  await ctx.dispose()
})

test("ingest mixed URLs — VentureBeat + YouTube", async ({ page }) => {
  await page.goto("/input")

  // The "Video URLs" tab is the default — find the textarea
  const textarea = page.getByRole("textbox", { name: /YouTube or Website URLs/i })
  await textarea.fill(`${VENTUREBEAT_URL}\n${YOUTUBE_URL}`)

  // Click ingest
  await page.getByRole("button", { name: /Ingest Videos/i }).click()

  // Wait for the success card — can take a while (Firecrawl + YouTube API)
  await expect(
    page.getByText(/Sources Ingested|Videos Ingested/i)
  ).toBeVisible({ timeout: 60_000 })
})

test("generate newsletter from ingested sources", async ({ page }) => {
  await page.goto("/input")

  // Re-enter the URLs (page may have reset between tests)
  const textarea = page.getByRole("textbox", { name: /YouTube or Website URLs/i })
  await textarea.fill(`${VENTUREBEAT_URL}\n${YOUTUBE_URL}`)
  await page.getByRole("button", { name: /Ingest Videos/i }).click()
  await expect(
    page.getByText(/Sources Ingested|Videos Ingested/i)
  ).toBeVisible({ timeout: 60_000 })

  // Generate newsletter
  await page.getByRole("button", { name: /Generate Newsletter/i }).click()

  // Wait for completion — LLM call can be slow
  await expect(
    page.getByText(/Newsletter Created/i)
  ).toBeVisible({ timeout: 120_000 })

  // View newsletter link should be present
  await expect(
    page.getByRole("link", { name: /View Newsletter/i })
  ).toBeVisible()
})

test("wiki pages created after ingest", async ({ page }) => {
  await page.goto("/wiki")

  // After auto-compile, at least one wiki page card should exist
  // The wiki page shows titles — wait for any badge or card to appear
  await expect(
    page.locator("[data-testid='wiki-page-card'], .wiki-card, h2, h3").first()
  ).toBeVisible({ timeout: 30_000 })
})

test("wiki health endpoint returns pages_checked > 0", async () => {
  const ctx = await request.newContext()
  const res = await ctx.get(`${BACKEND}/wiki/health`)
  expect(res.status()).toBe(200)

  const body = await res.json()
  expect(body.pages_checked).toBeGreaterThan(0)
  expect(typeof body.issue_count).toBe("number")

  await ctx.dispose()
})
```

- [ ] **Step 6.4: Add test script to `frontend/package.json`**

In `frontend/package.json`, add to the `"scripts"` section:
```json
"test:e2e": "playwright test"
```

- [ ] **Step 6.5: Ensure backend and frontend are running, then run tests**

In separate terminals (or use the existing running instances):
```bash
# Terminal 1: backend
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
uvicorn main:app --host 0.0.0.0 --port 8080

# Terminal 2: frontend
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npm run dev
```

Run tests:
```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npx playwright test --reporter=list 2>&1
```

Expected: 4 tests pass. Fix any failures before proceeding (see Troubleshooting below).

**Troubleshooting:**
- If the textarea label doesn't match: open browser devtools on `/input`, inspect the label text, update the `getByRole` query accordingly.
- If wiki test fails (no pages visible): check that auto-compile background task ran — `curl http://localhost:8080/wiki/stats` to see page counts. If 0, manually call `curl -X POST http://localhost:8080/wiki/compile -H "Content-Type: application/json" -d '{"user_id":"system"}'`.
- If Firecrawl returns no content: check `FIRECRAWL_API_KEY` in `backend/.env`. If missing, the httpx fallback will be used — it may fail on JS-heavy pages.

- [ ] **Step 6.6: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
git add frontend/playwright.config.ts frontend/tests/ frontend/package.json
git commit -m "feat: add Playwright E2E tests for ingest + newsletter + wiki flow"
```

---

## Task 7: README Update

**Files:**
- Modify: `README.md`

- [ ] **Step 7.1: Add "Supported Input Types" section to README**

In `README.md`, after the existing `## Architecture` section, add:

```markdown
## Supported Input Types

The **Video URLs** input accepts both YouTube links and website URLs on the same line:

| Type | Example |
|------|---------|
| YouTube video | `https://youtube.com/watch?v=abc123` |
| YouTube short URL | `https://youtu.be/abc123` |
| Website article | `https://venturebeat.com/data/karpathy-article` |
| Blog post | `https://example.com/blog/my-post` |

Mix and match freely — one URL per line. YouTube videos are transcribed via the YouTube API. Website URLs are scraped using [Firecrawl](https://www.firecrawl.dev).

### Firecrawl Setup

Set `FIRECRAWL_API_KEY` in `backend/.env` to enable full website scraping. Without a key, a lightweight httpx-based fallback is used (works for static pages, may fail on JS-heavy sites).

```env
FIRECRAWL_API_KEY=fc-your-key-here
```

### Wiki Knowledge Base

After every ingest, the wiki is automatically compiled. Each ingested source (video or article) is processed through concept extraction — the extracted concepts, tools, and patterns become wiki pages at `/wiki`.
```

- [ ] **Step 7.2: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
git add README.md
git commit -m "docs: add Supported Input Types section covering YouTube + website URLs"
```

---

## Final Verification

- [ ] **Run full backend unit suite**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python3 -m pytest tests/unit/ -v 2>&1 | tail -5
```

Expected: 130 tests pass.

- [ ] **Run frontend build**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Clear data and smoke test live ingest**

```bash
# Clear data
curl -X DELETE http://localhost:8080/admin/data

# Ingest VentureBeat article
curl -s -X POST http://localhost:8080/videos/ingest \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an", "https://www.youtube.com/watch?v=kwSVtQ7dziU"]}' \
  | python3 -m json.tool | head -30

# Check wiki stats (auto-compile runs in background — wait ~30s)
sleep 30
curl -s http://localhost:8080/wiki/stats | python3 -m json.tool
```

Expected: `pages_checked > 0` in wiki stats.

- [ ] **Run Playwright E2E tests**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npx playwright test --reporter=list
```

Expected: 4 tests pass.
