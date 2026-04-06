"""
Wiki filesystem store.

Reads and writes wiki pages to local_storage/wiki/ as Markdown files with
YAML frontmatter. This is the Phase A implementation — Supabase table storage
can be swapped in later by replacing only this module.

Directory layout:
    local_storage/wiki/
        concepts/<slug>.md
        tools/<slug>.md
        patterns/<slug>.md
        indexes/all.md
        health/
        qa_notes/
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

PAGE_TYPES = ("concept", "tool", "pattern")

_WIKI_ROOT = Path(__file__).resolve().parents[2] / "local_storage" / "wiki"

_TYPE_DIR = {
    "concept": _WIKI_ROOT / "concepts",
    "tool":    _WIKI_ROOT / "tools",
    "pattern": _WIKI_ROOT / "patterns",
    "index":   _WIKI_ROOT / "indexes",
    "health":  _WIKI_ROOT / "health",
    "qa_note": _WIKI_ROOT / "qa_notes",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class WikiPage:
    """In-memory representation of a single wiki page."""

    title: str
    slug: str
    page_type: str                        # concept | tool | pattern | index | health | qa_note
    content: str                          # Markdown body (no frontmatter)
    source_ids: list[str] = field(default_factory=list)   # video UUIDs that fed this page
    source_hash: str = ""                 # SHA-1 of sorted source_ids for dirty detection
    compiled_at: str = ""                 # ISO-8601 timestamp of last compile
    schema_version: int = SCHEMA_VERSION
    backlinks: list[str] = field(default_factory=list)    # [[Term]] cross-references found in content


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convert a display name to a URL/filename-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def compute_source_hash(source_ids: list[str]) -> str:
    """Stable SHA-1 hash of sorted source video IDs."""
    joined = ",".join(sorted(source_ids))
    return hashlib.sha1(joined.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Frontmatter serialisation
# ---------------------------------------------------------------------------

def _render(page: WikiPage) -> str:
    """Serialise a WikiPage to a Markdown string with YAML frontmatter."""
    sources_yaml = "\n".join(f"  - {s}" for s in page.source_ids)
    backlinks_yaml = "\n".join(f"  - \"{b}\"" for b in page.backlinks)
    compiled = page.compiled_at or _now()

    fm = (
        f"---\n"
        f"title: \"{page.title}\"\n"
        f"slug: {page.slug}\n"
        f"type: {page.page_type}\n"
        f"schema_version: {page.schema_version}\n"
        f"compiled_at: {compiled}\n"
        f"source_hash: {page.source_hash}\n"
        f"sources:\n{sources_yaml or '  []'}\n"
        f"backlinks:\n{backlinks_yaml or '  []'}\n"
        f"---\n\n"
    )
    return fm + page.content.strip() + "\n"


_FM_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)
_LIST_RE = re.compile(r"^\s+-\s+\"?(.+?)\"?\s*$", re.MULTILINE)
_SCALAR_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)


def _parse(raw: str) -> WikiPage:
    """Parse a Markdown string with YAML frontmatter into a WikiPage."""
    m = _FM_RE.match(raw)
    if not m:
        # No frontmatter — treat entire text as content.
        return WikiPage(title="", slug="", page_type="concept", content=raw)

    fm_block = m.group(1)
    content = raw[m.end():].strip()

    # Parse scalar fields.
    scalars: dict[str, str] = {}
    for key, val in _SCALAR_RE.findall(fm_block):
        scalars[key] = val.strip().strip('"')

    # Parse list fields (sources, backlinks) — they follow the key line.
    def _extract_list(key: str) -> list[str]:
        # Find the block after "key:\n" until the next non-indented line.
        pattern = re.compile(rf"^{key}:\s*\n((?:\s+-\s+.*\n)*)", re.MULTILINE)
        lm = pattern.search(fm_block)
        if not lm:
            return []
        return [x.strip().strip('"') for x in _LIST_RE.findall(lm.group(1)) if x.strip() not in ("[]", "")]

    return WikiPage(
        title=scalars.get("title", ""),
        slug=scalars.get("slug", ""),
        page_type=scalars.get("type", "concept"),
        schema_version=int(scalars.get("schema_version", SCHEMA_VERSION)),
        compiled_at=scalars.get("compiled_at", ""),
        source_hash=scalars.get("source_hash", ""),
        source_ids=_extract_list("sources"),
        backlinks=_extract_list("backlinks"),
        content=content,
    )


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _page_path(page_type: str, slug: str) -> Path:
    dir_ = _TYPE_DIR.get(page_type, _WIKI_ROOT / page_type)
    return dir_ / f"{slug}.md"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _ensure_dirs() -> None:
    for d in _TYPE_DIR.values():
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_page(page_type: str, slug: str) -> WikiPage | None:
    """Return a WikiPage from disk, or None if it doesn't exist."""
    path = _page_path(page_type, slug)
    if not path.exists():
        return None
    try:
        return _parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse wiki page %s: %s", path, exc)
        return None


def write_page(page: WikiPage) -> Path:
    """Write a WikiPage to disk. Returns the file path."""
    _ensure_dirs()
    page.compiled_at = _now()
    # Extract [[Backlink]] references from content.
    page.backlinks = re.findall(r"\[\[([^\]]+)\]\]", page.content)
    path = _page_path(page.page_type, page.slug)
    path.write_text(_render(page), encoding="utf-8")
    logger.debug("Wrote wiki page: %s", path)
    return path


def list_pages(page_type: str | None = None) -> list[WikiPage]:
    """List all wiki pages, optionally filtered by type."""
    _ensure_dirs()
    pages: list[WikiPage] = []
    types = [page_type] if page_type else list(PAGE_TYPES)
    for pt in types:
        dir_ = _TYPE_DIR.get(pt)
        if not dir_ or not dir_.exists():
            continue
        for path in sorted(dir_.glob("*.md")):
            page = read_page(pt, path.stem)
            if page:
                pages.append(page)
    return pages


def page_exists(page_type: str, slug: str) -> bool:
    return _page_path(page_type, slug).exists()


def needs_recompile(page_type: str, slug: str, source_ids: list[str]) -> bool:
    """Return True if the page is missing, stale, or on an old schema version."""
    existing = read_page(page_type, slug)
    if existing is None:
        return True
    if existing.schema_version < SCHEMA_VERSION:
        return True
    new_hash = compute_source_hash(source_ids)
    return existing.source_hash != new_hash


def wiki_stats() -> dict:
    """Return counts per page type and overall wiki metadata."""
    _ensure_dirs()
    stats: dict = {"total": 0, "by_type": {}}
    for pt in PAGE_TYPES:
        dir_ = _TYPE_DIR.get(pt)
        count = len(list(dir_.glob("*.md"))) if dir_ and dir_.exists() else 0
        stats["by_type"][pt] = count
        stats["total"] += count
    stats["wiki_root"] = str(_WIKI_ROOT)
    return stats


def write_index(content: str) -> Path:
    """Write the master index page."""
    _ensure_dirs()
    path = _TYPE_DIR["index"] / "all.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_health_report(content: str) -> Path:
    """Write a dated health report."""
    _ensure_dirs()
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    path = _TYPE_DIR["health"] / f"report-{date_str}.md"
    path.write_text(content, encoding="utf-8")
    return path
