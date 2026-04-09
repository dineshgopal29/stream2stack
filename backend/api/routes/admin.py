"""
Admin utility routes.

DELETE /admin/data — clear all ingested data and wiki pages.
Intended for development/testing only. Not rate-limited.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from db.supabase_client import get_supabase_client

router = APIRouter()
logger = logging.getLogger(__name__)

# Tables cleared in FK-safe order (children before parents)
_TABLES = ["newsletter_videos", "processed_videos", "newsletters", "videos"]

# Wiki filesystem root (same constant used by wiki_store.py)
_WIKI_ROOT = Path(__file__).resolve().parents[2] / "local_storage" / "wiki"


@router.delete(
    "/data",
    status_code=status.HTTP_200_OK,
    summary="Clear all ingested data",
    description=(
        "Deletes all rows from videos, newsletters, newsletter_videos, and "
        "processed_videos tables. Also removes the local_storage/wiki/ directory. "
        "For development and testing only."
    ),
)
async def clear_data() -> dict:
    supabase = get_supabase_client()

    cleared_tables: list[str] = []
    for table in _TABLES:
        try:
            if table in ("newsletter_videos",):
                supabase.table(table).delete().neq("newsletter_id", "").execute()
            elif table in ("processed_videos",):
                supabase.table(table).delete().neq("user_id", "").execute()
            else:
                supabase.table(table).delete().neq("id", "").execute()
            cleared_tables.append(table)
            logger.info("Cleared table: %s", table)
        except Exception as exc:
            logger.warning("Failed to clear table %s: %s", table, exc)

    # Remove wiki filesystem
    if _WIKI_ROOT.exists():
        shutil.rmtree(_WIKI_ROOT)
        logger.info("Removed wiki directory: %s", _WIKI_ROOT)

    return {"cleared": True, "tables": cleared_tables}
