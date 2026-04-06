"""
Wiki Q&A service — Phase B.

Answers free-form developer questions grounded in compiled wiki pages.
Each answer is filed back as a qa_note (a first-class wiki page).

Flow:
  1. Load all compiled wiki pages from the store.
  2. Score pages by keyword overlap with the question.
  3. Pass top-N pages as context to the LLM.
  4. Parse answer + cited sources from the LLM response.
  5. Write a qa_note to local_storage/wiki/qa_notes/.
  6. Return answer + source slugs + qa_note slug.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from services.blog_generator import _get_client, _chat
from services import wiki_store as store
from services.wiki_store import WikiPage, slugify

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_CONTEXT_PAGES = 8          # max wiki pages injected into prompt
_MAX_PAGE_CHARS = 1_500         # chars per page (truncated to save tokens)

_QA_SYSTEM_PROMPT = """\
You are a precise technical assistant. You answer developer questions using ONLY
the wiki pages provided below. Do not fabricate information not present in the
sources.

After your answer, include a "## Sources" section listing the slug paths of every
wiki page you drew from, one per line, prefixed with "- ":

## Sources
- concepts/retrieval-augmented-generation
- tools/langchain

If none of the provided pages are relevant, say so honestly rather than guessing.
"""


# ---------------------------------------------------------------------------
# Keyword relevance scorer
# ---------------------------------------------------------------------------

def _score_page(page: WikiPage, tokens: set[str]) -> int:
    """Count how many question tokens appear in the page title + content."""
    haystack = (page.title + " " + page.content).lower()
    return sum(1 for t in tokens if t in haystack)


def _top_pages(question: str, pages: list[WikiPage], n: int) -> list[WikiPage]:
    """Return the top-N pages most relevant to the question."""
    # Tokenise question: lowercase words, 3+ chars, ignore stop words.
    _STOP = {"the", "and", "for", "are", "how", "what", "why", "when",
              "does", "can", "use", "with", "this", "that", "from"}
    tokens = {w for w in re.findall(r"[a-z]{3,}", question.lower()) if w not in _STOP}
    if not tokens:
        return pages[:n]
    scored = [(p, _score_page(p, tokens)) for p in pages]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, score in scored[:n] if score > 0] or pages[:n]


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context(pages: list[WikiPage]) -> str:
    parts = []
    for p in pages:
        body = p.content[:_MAX_PAGE_CHARS]
        if len(p.content) > _MAX_PAGE_CHARS:
            body += "\n...[truncated]"
        parts.append(
            f"=== {p.page_type.upper()}: {p.title} (slug: {p.page_type}s/{p.slug}) ===\n{body}"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Source extractor
# ---------------------------------------------------------------------------

def _extract_sources(answer: str) -> tuple[str, list[str]]:
    """
    Split the LLM response into (clean_answer, [source_slugs]).
    Looks for a '## Sources' block at the end.
    """
    pattern = re.compile(r"\n## Sources\s*\n((?:\s*-\s+.+\n?)*)", re.IGNORECASE)
    m = pattern.search(answer)
    if not m:
        return answer.strip(), []
    sources_block = m.group(1)
    sources = [s.strip().lstrip("- ").strip() for s in sources_block.splitlines() if s.strip()]
    clean = answer[: m.start()].strip()
    return clean, sources


# ---------------------------------------------------------------------------
# QA note writer
# ---------------------------------------------------------------------------

def _write_qa_note(question: str, answer: str, sources: list[str]) -> str:
    """Write the Q&A pair as a qa_note wiki page. Returns the slug."""
    slug = slugify(question[:80])  # cap slug length
    sources_yaml = "\n".join(f"  - {s}" for s in sources)

    # Compose raw frontmatter + content manually (qa_note is a special type).
    from datetime import datetime, timezone
    compiled_at = datetime.now(tz=timezone.utc).isoformat()

    content = f"""---
title: "{question.replace('"', "'")}"
slug: {slug}
type: qa_note
schema_version: 1
compiled_at: {compiled_at}
source_hash: ""
sources:
{sources_yaml or "  []"}
backlinks:
  []
question: "{question.replace('"', "'")}"
---

## Question

{question}

## Answer

{answer}
"""

    from pathlib import Path
    qa_dir = store._TYPE_DIR["qa_note"]
    qa_dir.mkdir(parents=True, exist_ok=True)
    path = qa_dir / f"{slug}.md"
    path.write_text(content, encoding="utf-8")
    logger.info("Filed qa_note: %s", path)
    return slug


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def answer_question(question: str, user_id: str = "system") -> dict[str, Any]:
    """
    Answer a developer question from the compiled wiki.

    Returns:
        {
            "answer": str,
            "sources": list[str],       # wiki page slugs cited
            "qa_note_slug": str,        # filed qa_note slug
            "pages_searched": int,
        }
    """
    all_pages = store.list_pages()  # all compiled pages (concept + tool + pattern)

    if not all_pages:
        return {
            "answer": "The wiki has no compiled pages yet. Run POST /wiki/compile first.",
            "sources": [],
            "qa_note_slug": None,
            "pages_searched": 0,
        }

    relevant = _top_pages(question, all_pages, _MAX_CONTEXT_PAGES)
    context = _build_context(relevant)

    user_prompt = f"Wiki pages available:\n\n{context}\n\n---\n\nQuestion: {question}"

    client, model, backend = _get_client()
    raw_answer = _chat(
        client, model, backend,
        system=_QA_SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=1024,
        user_id=user_id,
        operation="wiki_query",
        resource_id=None,
    )

    answer, sources = _extract_sources(raw_answer)
    qa_slug = _write_qa_note(question, answer, sources)

    return {
        "answer": answer,
        "sources": sources,
        "qa_note_slug": qa_slug,
        "pages_searched": len(relevant),
    }
