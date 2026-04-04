"""
User settings routes.

GET /settings/{user_id} — retrieve user preferences.
PUT /settings/{user_id} — create or update user preferences.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from db.supabase_client import get_supabase_client
from models.schemas import UserSettings

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GET /settings/{user_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{user_id}",
    response_model=UserSettings,
    summary="Get user settings",
    description="Return the stored preferences for a given user.",
)
async def get_settings(user_id: str) -> UserSettings:
    supabase = get_supabase_client()

    try:
        result = (
            supabase.table("user_settings")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to fetch settings for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Database error: {exc}",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No settings found for user {user_id!r}. Use PUT to create them.",
        )

    return UserSettings(**result.data)


# ---------------------------------------------------------------------------
# PUT /settings/{user_id}
# ---------------------------------------------------------------------------


@router.put(
    "/{user_id}",
    response_model=UserSettings,
    summary="Create or update user settings",
    description=(
        "Upsert user preferences. If no settings record exists for this user it "
        "will be created; otherwise the existing record is updated."
    ),
)
async def upsert_settings(user_id: str, body: UserSettings) -> UserSettings:
    # Ensure path param and body user_id agree.
    if body.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Path user_id {user_id!r} does not match body user_id {body.user_id!r}."
            ),
        )

    supabase = get_supabase_client()

    record: dict[str, Any] = body.model_dump()

    try:
        result = (
            supabase.table("user_settings")
            .upsert(record, on_conflict="user_id")
            .execute()
        )
        upserted_data: list[dict[str, Any]] = result.data or []
    except Exception as exc:
        logger.exception("Failed to upsert settings for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Database error: {exc}",
        )

    if upserted_data:
        saved = upserted_data[0]
    else:
        # Fallback: fetch freshly if upsert returned no rows (Supabase RLS quirk).
        try:
            fetch_result = (
                supabase.table("user_settings")
                .select("*")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            saved = fetch_result.data or record
        except Exception as exc:
            logger.warning("Post-upsert fetch failed for user %s: %s", user_id, exc)
            saved = record

    logger.info("Settings upserted for user %s.", user_id)
    return UserSettings(**saved)
