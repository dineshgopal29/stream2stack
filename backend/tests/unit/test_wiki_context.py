"""Unit tests for services/wiki_context.py."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from unittest.mock import patch, MagicMock
from services.wiki_context import (
    get_relevant_pages,
    build_wiki_context_block,
    append_learn_more,
)
from services.wiki_store import WikiPage


def _make_page(title: str, slug: str, page_type: str, content: str = "Some content") -> WikiPage:
    return WikiPage(
        title=title,
        slug=slug,
        page_type=page_type,
        content=content,
        source_ids=["vid-1"],
        source_hash="abc123",
        compiled_at="2026-04-06T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# get_relevant_pages
# ---------------------------------------------------------------------------

def test_get_relevant_pages_returns_matching_concepts():
    rag_page = _make_page("RAG Pipeline", "rag-pipeline", "concept")

    def fake_read_page(page_type: str, slug: str):
        if page_type == "concept" and slug == "rag-pipeline":
            return rag_page
        return None

    with patch("services.wiki_context.store.read_page", side_effect=fake_read_page):
        pages = get_relevant_pages(
            concepts=["RAG Pipeline"],
            tools=[],
            patterns=[],
        )

    assert len(pages) == 1
    assert pages[0].title == "RAG Pipeline"


def test_get_relevant_pages_deduplicates():
    page = _make_page("LangChain", "langchain", "tool")

    def fake_read_page(page_type: str, slug: str):
        if page_type == "tool" and slug == "langchain":
            return page
        return None

    with patch("services.wiki_context.store.read_page", side_effect=fake_read_page):
        pages = get_relevant_pages(concepts=[], tools=["LangChain", "LangChain"], patterns=[])

    assert len(pages) == 1


def test_get_relevant_pages_respects_max_pages():
    def fake_read_page(page_type: str, slug: str):
        return _make_page(slug, slug, page_type)

    with patch("services.wiki_context.store.read_page", side_effect=fake_read_page):
        pages = get_relevant_pages(
            concepts=["a", "b", "c", "d", "e", "f"],
            tools=[],
            patterns=[],
            max_pages=3,
        )

    assert len(pages) == 3


def test_get_relevant_pages_returns_empty_when_no_wiki():
    with patch("services.wiki_context.store.read_page", return_value=None):
        pages = get_relevant_pages(concepts=["RAG"], tools=["LangChain"], patterns=["CQRS"])

    assert pages == []


def test_get_relevant_pages_never_raises():
    with patch("services.wiki_context.store.read_page", side_effect=Exception("disk error")):
        pages = get_relevant_pages(concepts=["RAG"], tools=[], patterns=[])

    assert pages == []


# ---------------------------------------------------------------------------
# build_wiki_context_block
# ---------------------------------------------------------------------------

def test_build_wiki_context_block_empty():
    assert build_wiki_context_block([]) == ""


def test_build_wiki_context_block_includes_title_and_content():
    pages = [_make_page("RAG Pipeline", "rag-pipeline", "concept", content="RAG content here")]
    block = build_wiki_context_block(pages)

    assert "RAG Pipeline" in block
    assert "RAG content here" in block
    assert "Wiki Context" in block


def test_build_wiki_context_block_truncates_long_content():
    long_content = "x" * 2000
    pages = [_make_page("Big Page", "big-page", "concept", content=long_content)]
    block = build_wiki_context_block(pages)

    assert len(block) < 1200


# ---------------------------------------------------------------------------
# append_learn_more
# ---------------------------------------------------------------------------

def test_append_learn_more_empty_pages():
    content = "# My Blog Post\n\nSome content."
    result = append_learn_more(content, [])
    assert result == content


def test_append_learn_more_appends_section():
    content = "# My Blog Post\n\nSome content."
    pages = [
        _make_page("RAG Pipeline", "rag-pipeline", "concept"),
        _make_page("LangChain", "langchain", "tool"),
    ]
    result = append_learn_more(content, pages)

    assert "## Learn More" in result
    assert "/wiki/concepts/rag-pipeline" in result
    assert "/wiki/tools/langchain" in result


def test_append_learn_more_preserves_original_content():
    content = "# My Blog Post\n\nSome content."
    pages = [_make_page("RAG Pipeline", "rag-pipeline", "concept")]
    result = append_learn_more(content, pages)

    assert result.startswith(content)
