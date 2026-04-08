"""Unit tests for services/wiki_linter.py."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from services.wiki_linter import LintIssue, LintReport, run_linter, _write_report
from services.wiki_store import WikiPage


def _make_page(
    title: str,
    slug: str,
    page_type: str,
    content: str = "## Summary\nContent.\n\n## Code Example\n```python\npass\n```",
    backlinks: list[str] | None = None,
    compiled_at: str | None = None,
) -> WikiPage:
    """Helper: build a WikiPage with sane defaults that pass all checks."""
    if compiled_at is None:
        compiled_at = datetime.now(timezone.utc).isoformat()
    return WikiPage(
        title=title,
        slug=slug,
        page_type=page_type,
        content=content,
        source_ids=["vid-1"],
        source_hash="abc123",
        compiled_at=compiled_at,
        backlinks=backlinks or [],
    )


def _run(pages: list[WikiPage]) -> LintReport:
    """Run linter with mocked store and write_health_report."""
    with patch("services.wiki_linter.store.list_pages", return_value=pages), \
         patch("services.wiki_linter.store.write_health_report", return_value=Path("/tmp/report.md")):
        return run_linter()


# ---------------------------------------------------------------------------
# missing_code_example
# ---------------------------------------------------------------------------

def test_missing_code_example_flagged():
    page = _make_page("RAG", "rag", "concept", content="## Summary\nNo code here.")
    report = _run([page])
    issues = [i for i in report.issues if i.check == "missing_code_example"]
    assert len(issues) == 1
    assert issues[0].slug == "rag"


def test_no_flag_when_code_example_present():
    page = _make_page("RAG", "rag", "concept")  # default content has ## Code Example
    report = _run([page])
    assert not any(i.check == "missing_code_example" for i in report.issues)


# ---------------------------------------------------------------------------
# stale_page
# ---------------------------------------------------------------------------

def test_stale_page_flagged():
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    page = _make_page("RAG", "rag", "concept", compiled_at=old)
    report = _run([page])
    issues = [i for i in report.issues if i.check == "stale_page"]
    assert len(issues) == 1
    assert "45" in issues[0].detail or "days" in issues[0].detail


def test_fresh_page_not_stale():
    recent = datetime.now(timezone.utc).isoformat()
    page = _make_page("RAG", "rag", "concept", compiled_at=recent)
    report = _run([page])
    assert not any(i.check == "stale_page" for i in report.issues)


# ---------------------------------------------------------------------------
# broken_backlink
# ---------------------------------------------------------------------------

def test_broken_backlink_flagged():
    page = _make_page("RAG", "rag", "concept", backlinks=["LangChain"])
    report = _run([page])
    issues = [i for i in report.issues if i.check == "broken_backlink"]
    assert len(issues) == 1
    assert "LangChain" in issues[0].detail


def test_valid_backlink_not_flagged():
    rag = _make_page("RAG", "rag", "concept", backlinks=["LangChain"])
    lc = _make_page("LangChain", "langchain", "tool", backlinks=[])
    report = _run([rag, lc])
    assert not any(i.check == "broken_backlink" for i in report.issues)


# ---------------------------------------------------------------------------
# contradiction_candidate
# ---------------------------------------------------------------------------

def test_contradiction_candidate_flagged():
    concept = _make_page("RAG", "rag", "concept")
    tool = _make_page("RAG", "rag", "tool")
    report = _run([concept, tool])
    issues = [i for i in report.issues if i.check == "contradiction_candidate"]
    assert len(issues) == 1
    assert issues[0].slug == "rag"


# ---------------------------------------------------------------------------
# report structure
# ---------------------------------------------------------------------------

def test_empty_wiki_returns_clean_report():
    report = _run([])
    assert report.pages_checked == 0
    assert report.issues == []
    assert report.by_check == {}


def test_by_check_counts_correctly():
    p1 = _make_page("RAG", "rag", "concept", content="## Summary\nNo code.")
    p2 = _make_page("CQRS", "cqrs", "pattern", content="## Summary\nNo code.")
    report = _run([p1, p2])
    assert report.by_check.get("missing_code_example", 0) == 2


# ---------------------------------------------------------------------------
# _write_report formatting
# ---------------------------------------------------------------------------

def test_write_report_clean():
    report = LintReport(
        generated_at="2026-04-07T00:00:00+00:00",
        pages_checked=5,
        issues=[],
        by_check={},
    )
    with patch("services.wiki_linter.store.write_health_report", return_value=Path("/tmp/r.md")) as mock_write:
        _write_report(report)
    content = mock_write.call_args[0][0]
    assert "Pages checked: 5" in content
    assert "✅ No issues found." in content


def test_write_report_with_issues():
    issue = LintIssue(
        check="missing_code_example",
        page_type="concept",
        slug="rag",
        title="RAG",
        detail="Page is missing a ## Code Example section",
    )
    report = LintReport(
        generated_at="2026-04-07T00:00:00+00:00",
        pages_checked=3,
        issues=[issue],
        by_check={"missing_code_example": 1},
    )
    with patch("services.wiki_linter.store.write_health_report", return_value=Path("/tmp/r.md")) as mock_write:
        _write_report(report)
    content = mock_write.call_args[0][0]
    assert "Issues found: 1" in content
    assert "Missing Code Example" in content
    assert "concept/rag" in content
