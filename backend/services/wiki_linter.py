"""
Wiki linter — structural health checks for the compiled wiki.

Runs four deterministic checks against the filesystem wiki store:
  1. missing_code_example    — page has no ## Code Example section
  2. stale_page              — compiled_at is older than 30 days
  3. broken_backlink         — [[Term]] in backlinks with no corresponding page
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
from services.wiki_store import slugify, WikiPage

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

def _check_missing_code_examples(pages: list[WikiPage]) -> list[LintIssue]:
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


def _check_stale_pages(pages: list[WikiPage]) -> list[LintIssue]:
    issues = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=_STALE_DAYS)
    for page in pages:
        if not page.compiled_at:
            continue
        try:
            compiled_dt = datetime.fromisoformat(page.compiled_at)
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


def _check_broken_backlinks(pages: list[WikiPage]) -> list[LintIssue]:
    existing_slugs: set[str] = {p.slug for p in pages}
    issues = []
    seen: set[tuple[str, str]] = set()

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


def _check_contradiction_candidates(pages: list[WikiPage]) -> list[LintIssue]:
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
                title=slug,  # No canonical title when same slug spans multiple types
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
