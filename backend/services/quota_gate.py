"""
Quota gate service.

Checks whether a user has remaining quota for a given resource before an
operation proceeds. Enforces hard blocks (HTTP 402), soft warnings (header),
and feature availability checks (HTTP 403).

Usage in a route:
    await QuotaGate("newsletters").check(user_id)
    await QuotaGate("emails").check(user_id)
    require_feature("email_send", plan_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Feature availability per plan.
# False / missing = not available on that plan.
_PLAN_FEATURES: dict[str, dict[str, bool]] = {
    "free": {
        "email_send":     False,
        "api_access":     False,
        "custom_prompts": False,
    },
    "pro": {
        "email_send":     True,
        "api_access":     True,
        "custom_prompts": False,
    },
    "team": {
        "email_send":     True,
        "api_access":     True,
        "custom_prompts": True,
    },
    "enterprise": {
        "email_send":     True,
        "api_access":     True,
        "custom_prompts": True,
    },
}

# Map resource names to their quota_ledger column names.
_LEDGER_COLUMNS: dict[str, str] = {
    "newsletters": "newsletters_used",
    "videos":      "videos_ingested",
    "emails":      "emails_sent",
    "scrapes":     "scrapes_used",
    "tokens":      "llm_tokens_used",
}

# Map resource names to their plan_quotas column names.
_PLAN_LIMIT_COLUMNS: dict[str, str] = {
    "newsletters": "newsletters_per_month",
    "videos":      "videos_per_month",
    "emails":      "emails_per_month",
    "scrapes":     "scrapes_per_month",
    "tokens":      "llm_tokens_per_month",
}

# Soft-warning threshold (fraction of limit used).
_WARN_THRESHOLD = 0.80

UPGRADE_URL = "https://stream2stack.com/pricing"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _current_period_start() -> str:
    """Return the first day of the current calendar month as ISO date string."""
    today = datetime.now(tz=timezone.utc)
    return today.strftime("%Y-%m-01")


def _get_user_plan(user_id: str) -> str:
    """Look up the user's plan_id from user_settings. Defaults to 'free'."""
    try:
        from db.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        result = (
            supabase.table("user_settings")
            .select("plan_id")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return (result.data or {}).get("plan_id", "free")
    except Exception as exc:
        logger.warning("Could not fetch plan for user %s: %s — defaulting to 'free'.", user_id, exc)
        return "free"


def _get_quota_data(user_id: str, period_start: str) -> dict:
    """Fetch current quota ledger row for (user_id, period_start).

    Returns a dict with ledger values (or zeros if no row exists yet).
    """
    try:
        from db.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        result = (
            supabase.table("quota_ledger")
            .select("*")
            .eq("user_id", user_id)
            .eq("period_start", period_start)
            .single()
            .execute()
        )
        return result.data or {}
    except Exception as exc:
        logger.warning("Could not fetch quota ledger for user %s: %s.", user_id, exc)
        return {}


def _get_plan_limits(plan_id: str) -> dict:
    """Fetch the plan_quotas row for plan_id."""
    try:
        from db.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        result = (
            supabase.table("plan_quotas")
            .select("*")
            .eq("plan_id", plan_id)
            .single()
            .execute()
        )
        return result.data or {}
    except Exception as exc:
        logger.warning("Could not fetch plan limits for plan %s: %s.", plan_id, exc)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class QuotaGate:
    """Checks and enforces a single resource quota for a user.

    Args:
        resource: One of 'newsletters', 'videos', 'emails', 'scrapes', 'tokens'.

    Usage:
        warning_header = await QuotaGate("newsletters").check(user_id)
        # Returns a dict to include in response headers, or empty dict.
    """

    def __init__(self, resource: str) -> None:
        if resource not in _LEDGER_COLUMNS:
            raise ValueError(f"Unknown quota resource: {resource!r}")
        self.resource = resource

    async def check(self, user_id: str) -> dict[str, str]:
        """Verify the user has remaining quota.

        Returns:
            A dict of response headers to attach (may be empty).
            ``{"X-Quota-Warning": "newsletters:14/20"}`` when at 80%+ usage.

        Raises:
            HTTPException(402) when quota is exhausted with no overage allowed.
        """
        import asyncio

        period_start = _current_period_start()
        plan_id, ledger, limits = await asyncio.gather(
            asyncio.to_thread(_get_user_plan, user_id),
            asyncio.to_thread(_get_quota_data, user_id, period_start),
            asyncio.to_thread(lambda: None),  # placeholder, resolved after plan_id
        )
        limits = await asyncio.to_thread(_get_plan_limits, plan_id)

        ledger_col = _LEDGER_COLUMNS[self.resource]
        limit_col  = _PLAN_LIMIT_COLUMNS[self.resource]

        used  = ledger.get(ledger_col, 0) or 0
        limit = limits.get(limit_col)       # None = unlimited

        headers: dict[str, str] = {}

        if limit is None:
            # Unlimited plan — always allow.
            return headers

        pct = used / limit if limit > 0 else 1.0

        if pct >= _WARN_THRESHOLD:
            headers["X-Quota-Warning"] = f"{self.resource}:{used}/{limit}"

        if used >= limit:
            overage_allowed: bool = limits.get("overage_allowed", False)
            if overage_allowed:
                logger.info(
                    "User %s in overage on %s (%d/%d, plan=%s).",
                    user_id, self.resource, used, limit, plan_id,
                )
                return headers  # allow, overage recorded via usage_events

            # Hard block.
            logger.warning(
                "Quota exhausted for user %s: %s %d/%d (plan=%s).",
                user_id, self.resource, used, limit, plan_id,
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code":        "quota_exceeded",
                    "resource":    self.resource,
                    "used":        used,
                    "limit":       limit,
                    "plan":        plan_id,
                    "upgrade_url": UPGRADE_URL,
                },
            )

        return headers


def require_feature(feature: str, plan_id: str) -> None:
    """Raise HTTP 403 if the named feature is not available on plan_id.

    Args:
        feature:  e.g. 'email_send', 'custom_prompts', 'api_access'
        plan_id:  e.g. 'free', 'pro', 'team', 'enterprise'

    Raises:
        HTTPException(403) when the feature is not on the given plan.
    """
    plan_features = _PLAN_FEATURES.get(plan_id, {})
    if not plan_features.get(feature, False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code":        "feature_not_available",
                "feature":     feature,
                "plan":        plan_id,
                "upgrade_url": UPGRADE_URL,
            },
        )


async def get_user_plan_id(user_id: str) -> str:
    """Async wrapper — look up plan_id from user_settings."""
    import asyncio
    return await asyncio.to_thread(_get_user_plan, user_id)
