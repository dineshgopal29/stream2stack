# Wiki Phase C Linter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a wiki health linter that detects structural issues (broken backlinks, missing code examples, stale pages, contradiction candidates) and exposes them via `GET /wiki/health`.

**Architecture:** A new `wiki_linter.py` service runs four deterministic checks against the filesystem wiki store, produces a `LintReport` dataclass, and writes a dated Markdown report to `local_storage/wiki/health/`. The `GET /wiki/health` endpoint in `wiki.py` wraps the linter in an async thread and returns the report as JSON. No LLM calls, no DB access — pure filesystem analysis.

**Tech Stack:** Python 3.11, dataclasses, FastAPI, pytest — no new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `backend/services/wiki_linter.py` | **New** — `LintIssue`, `LintReport`, `run_linter()` |
| `backend/tests/unit/test_wiki_linter.py` | **New** — 9 unit tests |
| `backend/api/routes/wiki.py` | **Modify** — add `GET /wiki/health` endpoint |
| `doc/wiki-knowledge-base.md` | **Modify** — Phase C marked Complete, version 0.5 added |
| `doc/wiki-knowledge-base.html` | **Modify** — Phase C badge Planned → Complete, v0.5 row |
| `tasks/todo.md` | **Modify** — Phase 9 added and checked |

---

## Task 1: wiki_linter.py Service

**Files:**
- Create: `backend/services/wiki_linter.py`
- Create: `backend/tests/unit/test_wiki_linter.py`

### Four checks implemented

| Check | Logic |
|-------|-------|
| `missing_code_example` | Page content does not contain `## Code Example` |
| `stale_page` | `compiled_at` is older than 30 days |
| `broken_backlink` | A `[[Term]]` in a page's `backlinks` list has no corresponding wiki page of any type |
| `contradiction_candidate` | Same slug exists under more than one page type (e.g. both concept and tool) |

- [ ] **Step 1.1: Write failing tests**

Create `backend/tests/unit/test_wiki_linter.py`:

```python
"""Unit tests for services/wiki_linter.py."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from services.wiki_linter import LintIssue, LintReport, run_linter
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
    # RAG page references LangChain but no LangChain page exists
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
```

- [ ] **Step 1.2: Run tests — verify they fail**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend && python3 -m pytest tests/unit/test_wiki_linter.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'services.wiki_linter'`

- [ ] **Step 1.3: Create `backend/services/wiki_linter.py`**

```python
"""
Wiki linter — structural health checks for the compiled wiki.

Runs four deterministic checks against the filesystem wiki store:
  1. missing_code_example — page has no ## Code Example section
  2. stale_page           — compiled_at is older than 30 days
  3. broken_backlink      — [[Term]] in backlinks with no corresponding page
  4. contradiction_candidate — same slug under multiple page types

No LLM calls, no DB access. Pure filesystem analysis.

Public API:
    run_linter() -> LintReport
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services import wiki_store as store
from services.wiki_store import slugify

logger = logging.getLogger(__name__)

_STALE_DAYS = 30


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LintIssue:
    check: str       # 'missing_code_example' | 'stale_page' | 'broken_backlink' | 'contradiction_candidate'
    page_type: str   # 'concept' | 'tool' | 'pattern' | 'mixed'
    slug: str
    title: str
    detail: str


@dataclass
class LintReport:
    generated_at: str
    pages_checked: int
    issues: list[LintIssue] = field(default_factory=list)
    by_check: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_missing_code_examples(pages: list) -> list[LintIssue]:
    issues = []
    for page in pages:
        if "## Code Example" not in page.content:
            issues.append(LintIssue(
                check="missing_code_example",
                page_type=page.page_type,
                slug=page.slug,
                title=page.title,
                detail="Page is missing a ## Code Example section",
            ))
    return issues


def _check_stale_pages(pages: list) -> list[LintIssue]:
    issues = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=_STALE_DAYS)
    for page in pages:
        if not page.compiled_at:
            continue
        try:
            compiled_dt = datetime.fromisoformat(page.compiled_at)
            # Ensure timezone-aware for comparison
            if compiled_dt.tzinfo is None:
                compiled_dt = compiled_dt.replace(tzinfo=timezone.utc)
            if compiled_dt < cutoff:
                age_days = (datetime.now(timezone.utc) - compiled_dt).days
                issues.append(LintIssue(
                    check="stale_page",
                    page_type=page.page_type,
                    slug=page.slug,
                    title=page.title,
                    detail=f"Not recompiled in {age_days} days (threshold: {_STALE_DAYS})",
                ))
        except (ValueError, TypeError) as exc:
            logger.warning("wiki_linter: could not parse compiled_at for %s/%s: %s", page.page_type, page.slug, exc)
    return issues


def _check_broken_backlinks(pages: list) -> list[LintIssue]:
    # Build the set of all slugs that have at least one page (any type)
    existing_slugs: set[str] = {p.slug for p in pages}
    issues = []
    seen: set[tuple[str, str]] = set()  # (source_slug, backlink_slug) — deduplicate

    for page in pages:
        for backlink_term in page.backlinks:
            backlink_slug = slugify(backlink_term)
            key = (page.slug, backlink_slug)
            if key in seen:
                continue
            seen.add(key)
            if backlink_slug not in existing_slugs:
                issues.append(LintIssue(
                    check="broken_backlink",
                    page_type=page.page_type,
                    slug=page.slug,
                    title=page.title,
                    detail=f"Backlink [[{backlink_term}]] has no corresponding wiki page",
                ))
    return issues


def _check_contradiction_candidates(pages: list) -> list[LintIssue]:
    # Same slug under multiple page types = potential conflicting definitions
    slug_types: dict[str, set[str]] = {}
    for page in pages:
        slug_types.setdefault(page.slug, set()).add(page.page_type)

    issues = []
    for slug, types in slug_types.items():
        if len(types) > 1:
            types_str = " + ".join(sorted(types))
            issues.append(LintIssue(
                check="contradiction_candidate",
                page_type="mixed",
                slug=slug,
                title=slug,
                detail=f"Same slug exists as multiple types: {types_str} — may indicate conflicting definitions",
            ))
    return issues


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def _write_report(report: LintReport) -> Path:
    lines = [
        "# Wiki Health Report\n",
        f"Generated: {report.generated_at}  ",
        f"Pages checked: {report.pages_checked}  ",
        f"Issues found: {len(report.issues)}\n",
    ]

    if not report.issues:
        lines.append("\n✅ No issues found.\n")
    else:
        by_check: dict[str, list[LintIssue]] = {}
        for issue in report.issues:
            by_check.setdefault(issue.check, []).append(issue)

        for check_name in sorted(by_check):
            check_issues = by_check[check_name]
            heading = check_name.replace("_", " ").title()
            lines.append(f"\n## {heading} ({len(check_issues)})\n")
            for issue in check_issues:
                lines.append(f"- **{issue.page_type}/{issue.slug}** — {issue.detail}")

    content = "\n".join(lines) + "\n"
    return store.write_health_report(content)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_linter() -> LintReport:
    """Run all wiki health checks and write a dated report to disk.

    Returns:
        LintReport with all issues found across all checks.
    """
    all_pages = store.list_pages()

    issues: list[LintIssue] = []
    issues += _check_missing_code_examples(all_pages)
    issues += _check_stale_pages(all_pages)
    issues += _check_broken_backlinks(all_pages)
    issues += _check_contradiction_candidates(all_pages)

    by_check: dict[str, int] = {}
    for issue in issues:
        by_check[issue.check] = by_check.get(issue.check, 0) + 1

    report = LintReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        pages_checked=len(all_pages),
        issues=issues,
        by_check=by_check,
    )

    _write_report(report)
    return report
```

- [ ] **Step 1.4: Run tests — verify they pass**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend && python3 -m pytest tests/unit/test_wiki_linter.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 1.5: Run full unit suite — verify no regressions**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend && python3 -m pytest tests/unit/ -v 2>&1 | tail -5
```

Expected: all tests pass (108 + 9 = 117 total).

- [ ] **Step 1.6: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack && git add backend/services/wiki_linter.py backend/tests/unit/test_wiki_linter.py
git commit -m "feat: add wiki_linter service with broken_backlink, missing_code_example, stale_page, contradiction_candidate checks"
```

---

## Task 2: GET /wiki/health Endpoint

**Files:**
- Modify: `backend/api/routes/wiki.py`

- [ ] **Step 2.1: Add import and response model to `wiki.py`**

At the top of `backend/api/routes/wiki.py`, add to the existing imports block:

```python
from dataclasses import asdict
from services import wiki_linter as linter_svc
```

After the existing `QueryResponse` model (around line 65), add:

```python
class LintIssueResponse(BaseModel):
    check: str
    page_type: str
    slug: str
    title: str
    detail: str


class HealthResponse(BaseModel):
    generated_at: str
    pages_checked: int
    issue_count: int
    by_check: dict[str, int]
    issues: list[LintIssueResponse]
```

- [ ] **Step 2.2: Add GET /wiki/health route**

Append to the end of `backend/api/routes/wiki.py`:

```python
@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Run wiki health check",
    description=(
        "Runs the wiki linter: checks for broken backlinks, missing code examples, "
        "stale pages, and contradiction candidates. Writes a dated Markdown report to "
        "local_storage/wiki/health/ and returns results as JSON."
    ),
)
async def wiki_health() -> HealthResponse:
    try:
        report = await asyncio.to_thread(linter_svc.run_linter)
        return HealthResponse(
            generated_at=report.generated_at,
            pages_checked=report.pages_checked,
            issue_count=len(report.issues),
            by_check=report.by_check,
            issues=[LintIssueResponse(**asdict(i)) for i in report.issues],
        )
    except Exception as exc:
        logger.exception("Wiki health check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
```

- [ ] **Step 2.3: Verify endpoint is reachable**

```bash
curl -s http://localhost:8080/wiki/health | python3 -m json.tool 2>&1 | head -20
```

Expected: JSON with `generated_at`, `pages_checked`, `issue_count`, `by_check`, `issues` fields. If the backend isn't running, start it first:

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend && uvicorn main:app --host 0.0.0.0 --port 8080 --reload &
```

- [ ] **Step 2.4: Verify endpoint appears in OpenAPI docs**

```bash
curl -s http://localhost:8080/openapi.json | python3 -c "import json,sys; spec=json.load(sys.stdin); print(list(spec['paths'].keys()))"
```

Expected: `/wiki/health` in the list of paths.

- [ ] **Step 2.5: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack && git add backend/api/routes/wiki.py
git commit -m "feat: add GET /wiki/health endpoint — runs linter and returns JSON report"
```

---

## Task 3: Update Design Docs

**Files:**
- Modify: `doc/wiki-knowledge-base.md`
- Modify: `doc/wiki-knowledge-base.html`
- Modify: `tasks/todo.md`

- [ ] **Step 3.1: Update `doc/wiki-knowledge-base.md`**

Change the Phase C header from:

```markdown
## Phase C — Linter (Planned)
```

to:

```markdown
## Phase C — Linter (Complete)
```

Add version 0.5 row to the version history table:

```markdown
| 0.5 | 2026-04-07 | Phase C complete — wiki_linter.py + GET /wiki/health endpoint |
```

- [ ] **Step 3.2: Update `doc/wiki-knowledge-base.html`**

Find the Phase C block and update the badge from:

```html
<h2>Phase C — Linter (Planned)</h2>
<div class="phase-block">
  <div class="phase-header">
    <h3>Health Checker</h3>
    <span class="badge badge-muted">Planned</span>
  </div>
```

to:

```html
<h2>Phase C — Linter (Complete)</h2>
<div class="phase-block">
  <div class="phase-header">
    <h3>Health Checker</h3>
    <span class="badge badge-green">Complete</span>
  </div>
```

Add version 0.5 row to the HTML version history table (after the 0.4 row):

```html
<tr><td>0.5</td><td>2026-04-07</td><td>Phase C complete — wiki_linter.py + GET /wiki/health endpoint</td></tr>
```

- [ ] **Step 3.3: Add Phase 9 to `tasks/todo.md`**

After the Phase 8 section, add:

```markdown
## Phase 9 — Wiki Linter (Phase C)
> See: doc/wiki-knowledge-base.md

- [x] backend/services/wiki_linter.py: LintIssue, LintReport, run_linter() with 4 checks
- [x] backend/api/routes/wiki.py: GET /wiki/health endpoint
```

- [ ] **Step 3.4: Commit**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack && git add doc/wiki-knowledge-base.md doc/wiki-knowledge-base.html tasks/todo.md
git commit -m "docs: mark Wiki Phase C complete in all tracking docs"
```

---

## Final Verification

- [ ] **Run full unit test suite**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend && python3 -m pytest tests/unit/ -v 2>&1 | tail -5
```

Expected: 117 tests pass (108 existing + 9 new wiki_linter tests).

- [ ] **Run frontend build to confirm no regressions**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Smoke test the endpoint**

```bash
curl -s http://localhost:8080/wiki/health | python3 -m json.tool
```

Expected output shape:
```json
{
  "generated_at": "2026-04-07T...",
  "pages_checked": 1,
  "issue_count": 2,
  "by_check": {
    "missing_code_example": 1,
    "stale_page": 1
  },
  "issues": [...]
}
```
