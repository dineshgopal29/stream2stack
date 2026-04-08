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


def test_extract_title_from_h1():
    md = "# My Article Title\n\nSome content here."
    assert _extract_title(md, "https://example.com") == "My Article Title"


def test_extract_title_fallback_to_hostname():
    md = "Just some text without a heading."
    assert _extract_title(md, "https://venturebeat.com/article") == "venturebeat.com"


def test_extract_title_strips_whitespace():
    md = "#   Padded Title  \n\nContent."
    assert _extract_title(md, "https://example.com") == "Padded Title"


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
