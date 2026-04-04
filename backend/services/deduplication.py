"""
Deduplication service.

Prevents the same video from appearing in multiple newsletters for a given
user, and detects semantically near-duplicate content via pgvector similarity.
"""

from __future__ import annotations

import logging
from typing import Any

from db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def is_processed(video_id: str, user_id: str) -> bool:
    """Check whether a video has already been included in a newsletter for a user.

    Queries the `processed_videos` table which records (user_id, video_id) pairs.

    Args:
        video_id: UUID of the video row in the `videos` table.
        user_id: The user's ID.

    Returns:
        True if the video has already been processed for this user.
    """
    supabase = get_supabase_client()
    try:
        result = (
            supabase.table("processed_videos")
            .select("video_id")
            .eq("video_id", video_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        exists = bool(result.data)
        logger.debug("is_processed(%s, %s) → %s", video_id, user_id, exists)
        return exists
    except Exception as exc:
        logger.error(
            "Failed to check processed_videos for video=%s user=%s: %s",
            video_id,
            user_id,
            exc,
        )
        # Fail open — do not accidentally exclude videos due to a DB error.
        return False


def mark_processed(video_id: str, user_id: str) -> None:
    """Record that a video has been processed for a user.

    Uses upsert to ensure idempotency.

    Args:
        video_id: UUID of the video row.
        user_id: The user's ID.
    """
    supabase = get_supabase_client()
    try:
        supabase.table("processed_videos").upsert(
            {"video_id": video_id, "user_id": user_id},
            on_conflict="video_id,user_id",
        ).execute()
        logger.info("Marked video %s as processed for user %s.", video_id, user_id)
    except Exception as exc:
        logger.error(
            "Failed to mark video=%s processed for user=%s: %s",
            video_id,
            user_id,
            exc,
        )
        raise


def check_similarity_duplicate(
    embedding: list[float],
    user_id: str,
    threshold: float = 0.85,
) -> bool:
    """Detect whether a semantically similar video has already been processed for this user.

    Calls a Supabase RPC function `match_processed_videos` that uses pgvector's
    cosine similarity operator (<->) to find near-duplicates among previously
    processed videos.

    Expected RPC signature (Postgres function):

        CREATE OR REPLACE FUNCTION match_processed_videos(
            query_embedding   vector(1536),
            match_threshold   float,
            user_id_filter    uuid
        )
        RETURNS TABLE (video_id uuid, similarity float)
        LANGUAGE sql
        AS $$
            SELECT pv.video_id, 1 - (v.embedding <-> query_embedding) AS similarity
            FROM processed_videos pv
            JOIN videos v ON v.id = pv.video_id
            WHERE pv.user_id = user_id_filter
              AND v.embedding IS NOT NULL
              AND 1 - (v.embedding <-> query_embedding) >= match_threshold
            LIMIT 1;
        $$;

    Args:
        embedding: The embedding vector of the candidate video.
        user_id: The user's ID.
        threshold: Cosine similarity threshold above which videos are considered
                   duplicates (default 0.85).

    Returns:
        True if a sufficiently similar video has already been processed.
    """
    supabase = get_supabase_client()
    try:
        result = supabase.rpc(
            "match_processed_videos",
            {
                "query_embedding": embedding,
                "match_threshold": threshold,
                "user_id_filter": user_id,
            },
        ).execute()

        is_dup = bool(result.data)
        if is_dup:
            logger.info(
                "Similarity duplicate found for user %s (threshold=%.2f).",
                user_id,
                threshold,
            )
        return is_dup

    except Exception as exc:
        logger.error(
            "Similarity duplicate check failed for user %s: %s",
            user_id,
            exc,
        )
        # Fail open — do not block valid content due to infrastructure issues.
        return False
