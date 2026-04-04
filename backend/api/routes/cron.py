"""
Cron / scheduled job routes.

These endpoints are designed to be called by an external scheduler
(cron job, Supabase Edge Function schedule, GitHub Actions, etc.).
They should be protected in production (e.g. shared secret header).

POST /cron/run     — Generate newsletters for all users due today.
POST /cron/digest  — Send monthly usage summary emails to all users.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status

from db.supabase_client import get_supabase_client

router = APIRouter()
logger = logging.getLogger(__name__)

_CRON_SECRET = os.getenv("CRON_SECRET", "")


def _verify_secret(x_cron_secret: str | None) -> None:
    """Reject requests that don't carry the shared cron secret.

    Pass CRON_SECRET= (empty) to disable auth in local dev.
    """
    if not _CRON_SECRET:
        return  # auth disabled — local dev
    if x_cron_secret != _CRON_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Cron-Secret header.",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_due(frequency: str, now: datetime) -> bool:
    """Return True if a user with this frequency should get a newsletter today."""
    if frequency == "daily":
        return True
    if frequency == "weekly":
        return now.weekday() == 0  # Monday
    if frequency == "monthly":
        return now.day == 1
    return False


# ---------------------------------------------------------------------------
# POST /cron/run
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    summary="Trigger scheduled newsletter generation",
    description=(
        "For each user whose delivery frequency is due today, generates a "
        "newsletter and emails it to their configured recipient address. "
        "Skips users with no recipient_email or no eligible videos."
    ),
)
async def cron_run(
    x_cron_secret: str | None = Header(None, alias="X-Cron-Secret"),
) -> dict[str, Any]:
    _verify_secret(x_cron_secret)

    supabase = get_supabase_client()
    now = datetime.now(tz=timezone.utc)

    # Fetch all users who have a recipient email set.
    try:
        result = (
            supabase.table("user_settings")
            .select("user_id, recipient_email, email_frequency")
            .not_.is_("recipient_email", "null")
            .neq("recipient_email", "")
            .execute()
        )
        users: list[dict] = result.data or []
    except Exception as exc:
        logger.exception("cron/run: failed to fetch user settings: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    due_users = [u for u in users if _is_due(u.get("email_frequency", "weekly"), now)]
    logger.info("cron/run: %d/%d users are due for %s.", len(due_users), len(users), now.date())

    results: list[dict[str, Any]] = []

    for user in due_users:
        user_id: str    = user["user_id"]
        email: str      = user["recipient_email"]
        freq: str       = user.get("email_frequency", "weekly")
        outcome: dict   = {"user_id": user_id, "frequency": freq}

        try:
            # Import here to avoid circular dependency at module level.
            from api.routes.newsletters import generate_newsletter
            from models.schemas import NewsletterGenerateRequest

            req = NewsletterGenerateRequest(
                user_id=user_id,
                auto_select=True,
                recipient_email=email,
            )
            newsletter = await generate_newsletter(req)
            outcome["status"]         = "sent"
            outcome["newsletter_id"]  = newsletter.id
            outcome["newsletter_title"] = newsletter.title
            logger.info("cron/run: sent newsletter to user %s (%s).", user_id, email)

        except HTTPException as exc:
            # Quota exceeded, no videos, dedup — non-fatal, skip this user.
            outcome["status"] = "skipped"
            outcome["reason"] = exc.detail
            logger.warning("cron/run: skipped user %s: %s", user_id, exc.detail)
        except Exception as exc:
            outcome["status"] = "error"
            outcome["reason"] = str(exc)
            logger.error("cron/run: error for user %s: %s", user_id, exc)

        results.append(outcome)

    sent    = sum(1 for r in results if r["status"] == "sent")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors  = sum(1 for r in results if r["status"] == "error")

    return {
        "run_at":      now.isoformat(),
        "users_due":   len(due_users),
        "sent":        sent,
        "skipped":     skipped,
        "errors":      errors,
        "results":     results,
    }


# ---------------------------------------------------------------------------
# POST /cron/digest
# ---------------------------------------------------------------------------


@router.post(
    "/digest",
    summary="Send monthly usage digest emails",
    description=(
        "For every user with a recipient email, fetches their current-month "
        "usage summary and cost breakdown, then emails a formatted digest. "
        "Intended to be called once per month (e.g. on the 1st at 08:00 UTC)."
    ),
)
async def cron_digest(
    x_cron_secret: str | None = Header(None, alias="X-Cron-Secret"),
) -> dict[str, Any]:
    _verify_secret(x_cron_secret)

    supabase = get_supabase_client()
    now = datetime.now(tz=timezone.utc)
    # Digest covers the *previous* month when run on the 1st.
    if now.day == 1 and now.month > 1:
        period = f"{now.year}-{now.month - 1:02d}"
    elif now.day == 1 and now.month == 1:
        period = f"{now.year - 1}-12"
    else:
        period = now.strftime("%Y-%m")  # current month for manual runs

    # Fetch users.
    try:
        result = (
            supabase.table("user_settings")
            .select("user_id, recipient_email")
            .not_.is_("recipient_email", "null")
            .neq("recipient_email", "")
            .execute()
        )
        users: list[dict] = result.data or []
    except Exception as exc:
        logger.exception("cron/digest: failed to fetch users: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    logger.info("cron/digest: sending usage digests to %d users for %s.", len(users), period)

    from services.email_service import send_usage_digest
    from services.quota_gate import _get_quota_data, _get_plan_limits, _get_user_plan
    from api.routes.usage import _next_month

    results: list[dict] = []

    for user in users:
        user_id: str  = user["user_id"]
        email: str    = user["recipient_email"]
        outcome: dict = {"user_id": user_id}

        try:
            period_start = f"{period}-01"
            period_end   = _next_month(period_start)

            plan_id = await asyncio.to_thread(_get_user_plan, user_id)
            limits  = await asyncio.to_thread(_get_plan_limits, plan_id)
            ledger  = await asyncio.to_thread(_get_quota_data, user_id, period_start)

            def _snap(used_key: str, limit_key: str) -> dict:
                used  = ledger.get(used_key, 0) or 0
                lim   = limits.get(limit_key)
                pct   = round(used / lim * 100, 1) if lim else None
                return {"used": used, "limit": lim, "pct": pct}

            summary = {
                "period": period,
                "plan":   plan_id,
                "quotas": {
                    "newsletters": _snap("newsletters_used",  "newsletters_per_month"),
                    "videos":      _snap("videos_ingested",   "videos_per_month"),
                    "emails":      _snap("emails_sent",       "emails_per_month"),
                    "scrapes":     _snap("scrapes_used",      "scrapes_per_month"),
                    "llm_tokens":  _snap("llm_tokens_used",   "llm_tokens_per_month"),
                },
                "cost_usd": {"accrued": float(ledger.get("cost_usd_accrued", 0) or 0)},
            }

            # Build cost breakdown from usage_events.
            events_result = (
                supabase.table("usage_events")
                .select("operation, input_tokens, output_tokens, total_tokens, cost_usd")
                .eq("user_id", user_id)
                .gte("created_at", period_start)
                .lt("created_at", period_end)
                .execute()
            )
            events = events_result.data or []

            from collections import defaultdict
            by_op: dict = defaultdict(lambda: {
                "input_tokens": 0, "output_tokens": 0,
                "total_tokens": 0, "cost_usd": 0.0, "call_count": 0,
            })
            grand_cost = 0.0
            for e in events:
                key = e.get("operation", "unknown")
                by_op[key]["input_tokens"]  += e.get("input_tokens", 0) or 0
                by_op[key]["output_tokens"] += e.get("output_tokens", 0) or 0
                by_op[key]["total_tokens"]  += e.get("total_tokens", 0) or 0
                by_op[key]["cost_usd"]      += float(e.get("cost_usd", 0) or 0)
                by_op[key]["call_count"]    += 1
                grand_cost += float(e.get("cost_usd", 0) or 0)

            cost_data = {
                "period":       period,
                "by_operation": dict(by_op),
                "totals":       {"cost_usd": round(grand_cost, 6), "total_tokens": 0, "call_count": len(events)},
            }

            await asyncio.to_thread(
                send_usage_digest,
                email, user_id, period, summary, cost_data,
            )
            outcome["status"] = "sent"
            logger.info("cron/digest: sent to %s.", email)

        except Exception as exc:
            outcome["status"] = "error"
            outcome["reason"] = str(exc)
            logger.error("cron/digest: error for user %s: %s", user_id, exc)

        results.append(outcome)

    sent   = sum(1 for r in results if r["status"] == "sent")
    errors = sum(1 for r in results if r["status"] == "error")

    return {
        "run_at":  now.isoformat(),
        "period":  period,
        "sent":    sent,
        "errors":  errors,
        "results": results,
    }
