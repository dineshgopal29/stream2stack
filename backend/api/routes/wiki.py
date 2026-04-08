"""
Wiki knowledge base routes.

POST /wiki/compile              — compile (or incrementally update) the wiki.
GET  /wiki/pages                — list all pages (filterable by type).
GET  /wiki/pages/{type}/{slug}  — fetch a single page.
GET  /wiki/stats                — counts per type, wiki root path.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from services import wiki_compiler as compiler_svc
from services import wiki_store as store
from services import wiki_query as query_svc
from services import wiki_linter as linter_svc

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CompileRequest(BaseModel):
    user_id: str = "system"
    force: bool = False
    video_ids: list[str] | None = None


class WikiPageResponse(BaseModel):
    title: str
    slug: str
    type: str
    content: str
    source_ids: list[str]
    source_hash: str
    compiled_at: str
    schema_version: int
    backlinks: list[str]


class CompileResponse(BaseModel):
    compiled: int
    skipped: int
    errors: int
    pages_written: int
    total_terms: int | None = None
    message: str | None = None


class QueryRequest(BaseModel):
    question: str
    user_id: str = "system"


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    qa_note_slug: str | None = None
    pages_searched: int


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(page: store.WikiPage) -> WikiPageResponse:
    return WikiPageResponse(
        title=page.title,
        slug=page.slug,
        type=page.page_type,
        content=page.content,
        source_ids=page.source_ids,
        source_hash=page.source_hash,
        compiled_at=page.compiled_at,
        schema_version=page.schema_version,
        backlinks=page.backlinks,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/compile",
    response_model=CompileResponse,
    status_code=status.HTTP_200_OK,
    summary="Compile the wiki",
    description=(
        "Runs the LLM compiler over all ingested videos and writes wiki pages "
        "to local_storage/wiki/. Incremental by default — only recompiles pages "
        "whose source videos have changed. Set force=True to recompile everything."
    ),
)
async def compile_wiki(body: CompileRequest) -> CompileResponse:
    try:
        result = await asyncio.to_thread(
            compiler_svc.compile_wiki,
            user_id=body.user_id,
            force=body.force,
            video_ids=body.video_ids,
        )
        return CompileResponse(**result)
    except Exception as exc:
        logger.exception("Wiki compile failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/pages",
    response_model=list[WikiPageResponse],
    summary="List wiki pages",
    description="List all compiled wiki pages. Filter by type: concept, tool, or pattern.",
)
async def list_pages(
    type: str | None = Query(None, description="Filter by page type: concept, tool, pattern"),
) -> list[WikiPageResponse]:
    if type and type not in store.PAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid type '{type}'. Must be one of: {', '.join(store.PAGE_TYPES)}",
        )
    pages = await asyncio.to_thread(store.list_pages, type)
    return [_to_response(p) for p in pages]


@router.get(
    "/pages/{page_type}/{slug}",
    response_model=WikiPageResponse,
    summary="Get a single wiki page",
)
async def get_page(page_type: str, slug: str) -> WikiPageResponse:
    if page_type not in store.PAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid type '{page_type}'. Must be one of: {', '.join(store.PAGE_TYPES)}",
        )
    page = await asyncio.to_thread(store.read_page, page_type, slug)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki page '{page_type}/{slug}' not found.",
        )
    return _to_response(page)


@router.get(
    "/stats",
    summary="Wiki statistics",
    description="Page counts per type and wiki root path.",
)
async def get_stats() -> dict:
    return await asyncio.to_thread(store.wiki_stats)


@router.post(
    "/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a question against the wiki",
    description=(
        "Answers a free-form developer question grounded in compiled wiki pages. "
        "The answer and its source citations are filed as a qa_note in "
        "local_storage/wiki/qa_notes/."
    ),
)
async def query_wiki(body: QueryRequest) -> QueryResponse:
    if not body.question.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="question must not be empty.",
        )
    try:
        result = await asyncio.to_thread(
            query_svc.answer_question,
            question=body.question,
            user_id=body.user_id,
        )
        return QueryResponse(**result)
    except Exception as exc:
        logger.exception("Wiki query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


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
