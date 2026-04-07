"""
Wiki context loader for blog/newsletter generation.

Slug-matches extracted concept/tool/pattern terms against compiled wiki pages
and returns relevant pages to inject as LLM context.

Public API:
    get_relevant_pages(concepts, tools, patterns, max_pages) -> list[WikiPage]
    build_wiki_context_block(pages) -> str
    append_learn_more(content, pages) -> str
"""
from __future__ import annotations

import logging
from services import wiki_store as store
from services.wiki_store import WikiPage, slugify

logger = logging.getLogger(__name__)

_MAX_PAGE_CHARS = 800  # chars per page in context block


def get_relevant_pages(
    concepts: list[str],
    tools: list[str],
    patterns: list[str],
    max_pages: int = 5,
) -> list[WikiPage]:
    """Slug-match extracted terms against compiled wiki pages.

    Returns up to max_pages pages in priority order: concepts → tools → patterns.
    Returns empty list if wiki has no matching pages (graceful degradation).
    Never raises — all exceptions are caught and logged.
    """
    seen: set[tuple[str, str]] = set()
    results: list[WikiPage] = []

    term_types = (
        [("concept", t) for t in concepts]
        + [("tool", t) for t in tools]
        + [("pattern", t) for t in patterns]
    )

    for page_type, term in term_types:
        if len(results) >= max_pages:
            break
        slug = slugify(term)
        key = (page_type, slug)
        if key in seen:
            continue
        seen.add(key)
        try:
            page = store.read_page(page_type, slug)
            if page:
                results.append(page)
        except Exception as exc:
            logger.warning("wiki_context: failed to read %s/%s: %s", page_type, slug, exc)

    return results


def build_wiki_context_block(pages: list[WikiPage]) -> str:
    """Format wiki pages as a context block for LLM injection.

    Returns empty string if pages is empty.
    Each page body is truncated to _MAX_PAGE_CHARS to control token usage.
    """
    if not pages:
        return ""

    parts = ["### Wiki Context\n\nRelevant pages from our knowledge base:\n"]
    for page in pages:
        body = page.content[:_MAX_PAGE_CHARS]
        if len(page.content) > _MAX_PAGE_CHARS:
            body += "\n...[truncated]"
        parts.append(
            f"=== {page.page_type.upper()}: {page.title} ===\n{body}"
        )
    return "\n\n".join(parts) + "\n"


def append_learn_more(content: str, pages: list[WikiPage]) -> str:
    """Append a ## Learn More section with wiki links to generated content.

    Returns content unchanged if pages is empty.
    Links use frontend /wiki/{type}/{slug} paths.
    """
    if not pages:
        return content

    lines = ["\n\n## Learn More\n"]
    for page in pages:
        path = f"/wiki/{page.page_type}s/{page.slug}"
        lines.append(f"- [{page.title}]({path})")

    return content + "\n".join(lines) + "\n"
