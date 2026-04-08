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
_DESCRIPTION_MAX_CHARS = 300


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
            return stripped[:_DESCRIPTION_MAX_CHARS]
    return ""


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
