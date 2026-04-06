"""
Wiki compiler service.

Reads all ingested videos from the DB, extracts concepts/tools/patterns,
groups them across videos, and compiles one Markdown wiki page per unique term.

Incremental: a page is only recompiled when its source video set changes
(detected via source_hash) or the schema version advances.

Compile flow:
  1. Fetch all videos with transcripts from DB.
  2. Run concept extraction per video (LLM call, reuses concept_extraction.py).
  3. Build an inverted index: term → list[video].
  4. For each term, call the LLM to write/update a wiki page.
  5. Write a master index page.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any, Optional

from db.supabase_client import get_supabase_client
from services import concept_extraction as concept_svc
from services.blog_generator import _get_client, _chat  # reuse LLM routing
from services import wiki_store as store
from services.wiki_store import WikiPage, slugify, compute_source_hash

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wiki page LLM prompt
# ---------------------------------------------------------------------------

_WIKI_SYSTEM_PROMPT = """\
You are a technical knowledge base compiler. Your job is to synthesise
information from multiple video transcripts and concept metadata into a single,
comprehensive, standalone wiki page about a specific technical term.

Write for developers who write code every day. Assume baseline familiarity with
software engineering but not necessarily with this specific term.

Always respond with ONLY the Markdown body — no YAML frontmatter, no title
heading (it is added automatically), no surrounding fences.

The page MUST follow this exact structure:

## Summary
One crisp paragraph. Define what it is (negation before affirmation if helpful).
State why a developer should care.

## How It Works
Concrete explanation. Use an analogy if it helps. Keep it accurate.

## Code Example
Include at least one real or illustrative code block. Use Python unless the
context clearly calls for another language. Add inline comments explaining *why*.

```python
# Example code here
```

## Patterns & Pitfalls
3–5 bullet points mixing best practices with common mistakes. Label clearly:
- ✓ Do: ...
- ✗ Don't: ...

## Related Concepts
Cross-reference other terms using [[Double Bracket]] syntax (exactly two square
brackets around the term name, as it would appear in this knowledge base):
- [[Related Term One]]
- [[Related Term Two]]

Guidelines:
- If sources contradict each other, capture both perspectives honestly.
- Never fabricate specific benchmark numbers or claims not in the sources.
- Prefer concrete examples over abstract definitions.
- Target 300–600 words.
"""


def _build_compile_prompt(term: str, page_type: str, videos: list[dict[str, Any]]) -> str:
    """Build the user prompt for compiling a single wiki page."""
    parts = [
        f"Compile a wiki page for the {page_type}: **{term}**\n",
        f"The following {len(videos)} video(s) mention this {page_type}:\n",
    ]
    for i, v in enumerate(videos, 1):
        title = v.get("title", "Untitled")
        transcript = (v.get("transcript") or "")[:3_000]  # cap per-video context
        concepts = v.get("_concepts")
        meta = ""
        if concepts:
            meta = (
                f"  Extracted metadata — "
                f"concepts: {', '.join(concepts.concepts[:5])}; "
                f"tools: {', '.join(concepts.tools[:5])}; "
                f"patterns: {', '.join(concepts.patterns[:5])}"
            )
        parts.append(
            f"--- Source {i}: {title} ---\n"
            + (meta + "\n" if meta else "")
            + f"Transcript excerpt:\n{transcript}\n"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_concepts_for_video(video: dict[str, Any], user_id: str):
    """Run concept extraction and attach results to the video dict in-place."""
    transcript = video.get("transcript") or ""
    title = video.get("title") or "Untitled"
    if not transcript:
        return None
    try:
        result = concept_svc.extract_concepts(transcript, title, user_id)
        video["_concepts"] = result
        return result
    except Exception as exc:
        logger.warning("Concept extraction failed for video %s: %s", video.get("id"), exc)
        return None


def _compile_page(
    term: str,
    page_type: str,
    videos: list[dict[str, Any]],
    client,
    model: str,
    backend: str,
    user_id: str,
) -> WikiPage:
    """Call the LLM to compile a single wiki page for one term."""
    slug = slugify(term)
    source_ids = [v["id"] for v in videos]
    user_prompt = _build_compile_prompt(term, page_type, videos)

    content = _chat(
        client, model, backend,
        system=_WIKI_SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=1536,
        user_id=user_id,
        operation="wiki_compile",
        resource_id=None,
    )

    return WikiPage(
        title=term,
        slug=slug,
        page_type=page_type,
        content=content,
        source_ids=source_ids,
        source_hash=compute_source_hash(source_ids),
    )


def _build_index(term_map: dict[str, dict[str, list[str]]]) -> str:
    """Build a master index Markdown page."""
    lines = [
        "# Wiki Knowledge Base — Index\n",
        f"*Auto-generated. Last compiled: see individual pages.*\n",
    ]
    for page_type, terms in sorted(term_map.items()):
        lines.append(f"\n## {page_type.title()}s\n")
        for term in sorted(terms.keys()):
            slug = slugify(term)
            lines.append(f"- [{term}]({page_type}s/{slug}.md)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_wiki(
    user_id: str = "system",
    force: bool = False,
    video_ids: Optional[list[str]] = None,
) -> dict:
    """Compile (or incrementally update) the entire wiki.

    Args:
        user_id:   User triggering the compile (for metering).
        force:     Recompile all pages even if source_hash is unchanged.
        video_ids: Restrict to specific video UUIDs (for targeted recompile).

    Returns:
        A summary dict: {compiled, skipped, errors, pages_written}.
    """
    supabase = get_supabase_client()
    client, model, backend = _get_client()

    # 1. Fetch videos.
    try:
        query = supabase.table("videos").select("*").not_.is_("transcript", "null")
        if video_ids:
            query = query.in_("id", video_ids)
        result = query.execute()
        videos: list[dict[str, Any]] = result.data or []
    except Exception as exc:
        logger.error("Failed to fetch videos for wiki compile: %s", exc)
        raise

    if not videos:
        return {"compiled": 0, "skipped": 0, "errors": 0, "pages_written": 0, "message": "No videos with transcripts found."}

    logger.info("Wiki compile: processing %d videos (force=%s).", len(videos), force)

    # 2. Extract concepts per video.
    for video in videos:
        _extract_concepts_for_video(video, user_id)

    # 3. Build inverted index: {page_type: {term: [videos]}}
    term_map: dict[str, dict[str, list[dict]]] = {
        "concept": defaultdict(list),
        "tool":    defaultdict(list),
        "pattern": defaultdict(list),
    }
    for video in videos:
        concepts = video.get("_concepts")
        if not concepts:
            continue
        for term in concepts.concepts:
            term_map["concept"][term].append(video)
        for term in concepts.tools:
            term_map["tool"][term].append(video)
        for term in concepts.patterns:
            term_map["pattern"][term].append(video)

    # 4. Compile pages — skip if source_hash unchanged (unless force=True).
    compiled = skipped = errors = 0

    for page_type, terms in term_map.items():
        for term, contributing_videos in terms.items():
            slug = slugify(term)
            source_ids = [v["id"] for v in contributing_videos]

            if not force and not store.needs_recompile(page_type, slug, source_ids):
                logger.debug("Skipping %s/%s (up to date).", page_type, slug)
                skipped += 1
                continue

            logger.info("Compiling %s page: %s (from %d videos).", page_type, term, len(contributing_videos))
            try:
                page = _compile_page(term, page_type, contributing_videos, client, model, backend, user_id)
                store.write_page(page)
                compiled += 1
            except Exception as exc:
                logger.error("Failed to compile %s/%s: %s", page_type, term, exc)
                errors += 1

    # 5. Write master index.
    index_term_map = {pt: {t: [v["id"] for v in vs] for t, vs in terms.items()} for pt, terms in term_map.items()}
    store.write_index(_build_index(index_term_map))

    pages_written = compiled
    logger.info(
        "Wiki compile complete: %d compiled, %d skipped, %d errors.",
        compiled, skipped, errors,
    )
    return {
        "compiled": compiled,
        "skipped": skipped,
        "errors": errors,
        "pages_written": pages_written,
        "total_terms": sum(len(t) for t in term_map.values()),
    }
