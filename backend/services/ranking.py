"""
Video ranking and selection service.

Scores videos based on a weighted combination of semantic relevance to the
user's topic interests and recency of publication, then selects the top-N.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two dense vectors.

    Args:
        a: First embedding vector.
        b: Second embedding vector.

    Returns:
        Cosine similarity in the range [-1, 1]. Returns 0.0 if either vector
        has zero magnitude.
    """
    va = np.array(a, dtype=np.float64)
    vb = np.array(b, dtype=np.float64)

    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)

    if norm_a == 0.0 or norm_b == 0.0:
        logger.warning("Zero-magnitude vector passed to cosine_similarity — returning 0.")
        return 0.0

    return float(np.dot(va, vb) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Recency helpers
# ---------------------------------------------------------------------------


def days_since_published(published_at: str | datetime) -> float:
    """Return the number of days elapsed since a video was published.

    Args:
        published_at: ISO-8601 datetime string (e.g. "2024-06-15T10:00:00Z")
                      or a datetime object (psycopg2 returns timestamptz as datetime).

    Returns:
        Floating-point number of days. Returns a large sentinel value (3650)
        if the date cannot be parsed.
    """
    try:
        if isinstance(published_at, datetime):
            # psycopg2 returns timestamptz columns as datetime objects.
            pub_dt = published_at
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        else:
            # Handle both "Z" suffix and "+00:00" offset strings.
            if published_at.endswith("Z"):
                published_at = published_at[:-1] + "+00:00"
            pub_dt = datetime.fromisoformat(published_at)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        delta = now - pub_dt
        return max(0.0, delta.total_seconds() / 86_400)
    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning("Could not parse published_at %r: %s. Defaulting to 3650 days.", published_at, exc)
        return 3_650.0


def recency_score(published_at: str) -> float:
    """Convert a publication date into a normalised recency score.

    Uses the formula: score = 1 / (1 + days_since_published), which gives:
      - A video published today → ~1.0
      - A video published 1 week ago → ~0.13
      - A video published 1 year ago → ~0.003

    Args:
        published_at: ISO-8601 datetime string.

    Returns:
        Score in the range (0, 1].
    """
    days = days_since_published(published_at)
    return 1.0 / (1.0 + days)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_video(video: dict[str, Any], user_topics_embedding: list[float]) -> float:
    """Compute a composite relevance + recency score for a single video.

    Formula:
        score = (recency_score * 0.4) + (cosine_similarity * 0.6)

    Args:
        video: A video dict containing at least `published_at` and `embedding`
               fields (both may be None/missing).
        user_topics_embedding: The user's topics embedding vector.

    Returns:
        Score in the range [0, 1]. Videos missing embeddings or published_at
        will receive lower scores but are not excluded.
    """
    # Recency component
    published_at = video.get("published_at") or ""
    r_score = recency_score(published_at) if published_at else 0.0

    # Similarity component
    embedding = video.get("embedding")
    if embedding and user_topics_embedding:
        try:
            sim = cosine_similarity(embedding, user_topics_embedding)
            # Clamp to [0, 1] — cosine similarity can be negative.
            sim = max(0.0, sim)
        except Exception as exc:
            logger.warning("cosine_similarity failed for video %s: %s", video.get("id"), exc)
            sim = 0.0
    else:
        sim = 0.0

    composite = (r_score * 0.4) + (sim * 0.6)
    logger.debug(
        "Video %s: recency=%.4f, similarity=%.4f, composite=%.4f",
        video.get("id", "?"),
        r_score,
        sim,
        composite,
    )
    return composite


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def rank_and_select(
    videos: list[dict[str, Any]],
    user_topics_embedding: list[float],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Rank videos by composite score and return the top-N.

    Args:
        videos: List of video dicts from the database.
        user_topics_embedding: Embedding of the user's interest topics.
        top_n: Maximum number of videos to return.

    Returns:
        Sorted list of up to top_n video dicts (highest scoring first).
    """
    if not videos:
        return []

    scored = [
        (score_video(v, user_topics_embedding), v)
        for v in videos
    ]
    scored.sort(key=lambda t: t[0], reverse=True)

    selected = [v for _, v in scored[:top_n]]
    logger.info(
        "Ranked %d videos; selected top %d. Scores: %s",
        len(videos),
        len(selected),
        [f"{s:.4f}" for s, _ in scored[:top_n]],
    )
    return selected


def select_cohesive_top_n(
    videos: list[dict[str, Any]],
    n: int = 3,
) -> list[dict[str, Any]]:
    """Return the n videos closest to the group embedding centroid.

    Algorithm:
      1. Separate into has_embedding / no_embedding groups.
      2. If no embeddings at all, fall back to top-n by recency (desc).
      3. Compute centroid = mean of all embedding vectors.
      4. Score each embedded video by cosine_similarity(embedding, centroid).
      5. Return top-n scored, padded with no_embedding videos if needed.

    Args:
        videos: List of video dicts, each optionally containing an 'embedding' list.
        n:      Maximum number of videos to return.

    Returns:
        Up to n videos, ordered by closeness to group centroid.
    """
    if not videos:
        return []
    if len(videos) <= n:
        return videos

    has_emb = [v for v in videos if v.get("embedding")]
    no_emb  = [v for v in videos if not v.get("embedding")]

    if not has_emb:
        sorted_by_recency = sorted(
            videos,
            key=lambda v: v.get("published_at") or "",
            reverse=True,
        )
        return sorted_by_recency[:n]

    emb_matrix = np.array([v["embedding"] for v in has_emb], dtype=np.float64)
    centroid: list[float] = emb_matrix.mean(axis=0).tolist()

    scored: list[tuple[float, dict[str, Any]]] = [
        (cosine_similarity(v["embedding"], centroid), v)
        for v in has_emb
    ]
    scored.sort(key=lambda t: t[0], reverse=True)

    result = [v for _, v in scored[:n]]

    if len(result) < n:
        result.extend(no_emb[: n - len(result)])

    logger.info(
        "select_cohesive_top_n: %d input → %d selected (n=%d). Top scores: %s",
        len(videos),
        len(result),
        n,
        [f"{s:.4f}" for s, _ in scored[:n]],
    )
    return result[:n]
