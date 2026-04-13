"""
Usage metering API routes.

GET /usage/summary   — current quota snapshot for a user.
GET /usage/events    — paginated raw event log.
GET /usage/cost      — cost breakdown by operation for a billing period.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from db.supabase_client import get_supabase_client
from services.quota_gate import _current_period_start, _get_plan_limits, _get_user_plan

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GET /usage/summary
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    summary="Usage quota snapshot",
    description=(
        "Returns the user's current quota usage for the active billing period, "
        "their plan limits, and accumulated AI cost."
    ),
)
async def get_usage_summary(
    user_id: str = Query(..., description="The user's ID."),
) -> dict[str, Any]:
    import asyncio

    period_start = _current_period_start()
    plan_id      = await asyncio.to_thread(_get_user_plan, user_id)
    limits       = await asyncio.to_thread(_get_plan_limits, plan_id)

    supabase = get_supabase_client()
    try:
        ledger_result = (
            supabase.table("quota_ledger")
            .select("*")
            .eq("user_id", user_id)
            .eq("period_start", period_start)
            .single()
            .execute()
        )
        ledger = ledger_result.data or {}
    except Exception:
        ledger = {}

    def _snapshot(used_key: str, limit_key: str) -> dict[str, Any]:
        used  = ledger.get(used_key, 0) or 0
        limit = limits.get(limit_key)     # None = unlimited
        pct   = round(used / limit * 100, 1) if limit else None
        return {"used": used, "limit": limit, "pct": pct}

    return {
        "period":  period_start[:7],          # "YYYY-MM"
        "plan":    plan_id,
        "quotas": {
            "newsletters": _snapshot("newsletters_used",  "newsletters_per_month"),
            "videos":      _snapshot("videos_ingested",   "videos_per_month"),
            "emails":      _snapshot("emails_sent",       "emails_per_month"),
            "scrapes":     _snapshot("scrapes_used",      "scrapes_per_month"),
            "llm_tokens":  _snapshot("llm_tokens_used",   "llm_tokens_per_month"),
        },
        "cost_usd": {
            "accrued": float(ledger.get("cost_usd_accrued", 0) or 0),
        },
    }


# ---------------------------------------------------------------------------
# GET /usage/events
# ---------------------------------------------------------------------------


@router.get(
    "/events",
    summary="Raw usage event log",
    description="Returns paginated usage events for a user, newest first.",
)
async def get_usage_events(
    user_id: str = Query(..., description="The user's ID."),
    event_type: Optional[str] = Query(None, description="Filter by event_type."),
    operation: Optional[str] = Query(None, description="Filter by operation."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    supabase = get_supabase_client()
    try:
        query = (
            supabase.table("usage_events")
            .select(
                "id, event_type, operation, model, input_tokens, output_tokens, "
                "total_tokens, cost_usd, resource_id, created_at"
            )
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if event_type:
            query = query.eq("event_type", event_type)
        if operation:
            query = query.eq("operation", operation)

        result = query.execute()
        return result.data or []
    except Exception as exc:
        logger.exception("Failed to fetch usage events for user %s: %s", user_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /usage/cost
# ---------------------------------------------------------------------------


@router.get(
    "/cost",
    summary="Cost breakdown by operation",
    description="Returns aggregated AI costs grouped by operation for a billing period.",
)
async def get_usage_cost(
    user_id: str = Query(..., description="The user's ID."),
    period: Optional[str] = Query(
        None,
        description="Billing period as YYYY-MM (defaults to current month).",
    ),
) -> dict[str, Any]:
    if period:
        try:
            # Normalise to first-of-month format
            from datetime import datetime
            dt = datetime.strptime(period, "%Y-%m")
            period_start = dt.strftime("%Y-%m-01")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="period must be in YYYY-MM format.",
            )
    else:
        period_start = _current_period_start()

    period_end = _next_month(period_start)

    supabase = get_supabase_client()
    try:
        result = (
            supabase.table("usage_events")
            .select("operation, model, input_tokens, output_tokens, total_tokens, cost_usd, created_at")
            .eq("user_id", user_id)
            .execute()
        )
        raw_events: list[dict] = result.data or []
    except Exception as exc:
        logger.exception("Failed to fetch cost data for user %s: %s", user_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    events = [
        event for event in raw_events
        if period_start <= str(event.get("created_at") or "") < period_end
    ]

    # Aggregate in Python — Supabase JS doesn't expose GROUP BY cleanly.
    from collections import defaultdict
    by_op: dict[str, dict] = defaultdict(lambda: {
        "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
        "cost_usd": 0.0, "call_count": 0,
    })
    grand_cost = 0.0
    grand_tokens = 0

    for e in events:
        key = e.get("operation", "unknown")
        bucket = by_op[key]
        bucket["input_tokens"]  += e.get("input_tokens", 0) or 0
        bucket["output_tokens"] += e.get("output_tokens", 0) or 0
        bucket["total_tokens"]  += e.get("total_tokens", 0) or 0
        bucket["cost_usd"]      += float(e.get("cost_usd", 0) or 0)
        bucket["call_count"]    += 1
        grand_cost   += float(e.get("cost_usd", 0) or 0)
        grand_tokens += e.get("total_tokens", 0) or 0

    return {
        "period":       period_start[:7],
        "by_operation": dict(by_op),
        "totals": {
            "cost_usd":    round(grand_cost, 6),
            "total_tokens": grand_tokens,
            "call_count":  len(events),
        },
    }


def _next_month(period_start: str) -> str:
    """Return the first day of the month after period_start (YYYY-MM-01)."""
    from datetime import date
    d = date.fromisoformat(period_start)
    if d.month == 12:
        return f"{d.year + 1}-01-01"
    return f"{d.year}-{d.month + 1:02d}-01"
