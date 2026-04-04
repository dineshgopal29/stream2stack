"""
Unit tests for services/ranking.py.

No external dependencies — all tests run without a database or API key.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from services.ranking import (
    cosine_similarity,
    days_since_published,
    rank_and_select,
    recency_score,
    score_video,
)


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors():
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_arbitrary_vectors():
    # [1,1] and [1,0]: angle = 45° → cos(45°) = √2/2 ≈ 0.7071
    result = cosine_similarity([1.0, 1.0], [1.0, 0.0])
    assert result == pytest.approx(math.sqrt(2) / 2, abs=1e-6)


def test_cosine_similarity_zero_vector_returns_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_both_zero_vectors():
    assert cosine_similarity([0.0], [0.0]) == 0.0


# ---------------------------------------------------------------------------
# days_since_published / recency_score
# ---------------------------------------------------------------------------


def test_days_since_published_today():
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    days = days_since_published(now_iso)
    assert 0.0 <= days < 0.01  # within a second


def test_days_since_published_one_week_ago():
    one_week_ago = (datetime.now(tz=timezone.utc) - timedelta(days=7)).isoformat()
    days = days_since_published(one_week_ago)
    assert 6.9 < days < 7.1


def test_days_since_published_z_suffix():
    # YouTube API returns "Z" suffix, not "+00:00"
    one_week_ago = (datetime.now(tz=timezone.utc) - timedelta(days=7)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    days = days_since_published(one_week_ago)
    assert 6.9 < days < 7.1


def test_days_since_published_invalid_returns_sentinel():
    assert days_since_published("not-a-date") == pytest.approx(3650.0)


def test_recency_score_today_is_near_one():
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    score = recency_score(now_iso)
    assert score > 0.99


def test_recency_score_old_date_is_near_zero():
    old = "2000-01-01T00:00:00Z"
    score = recency_score(old)
    assert score < 0.01


def test_recency_score_formula():
    # Exactly 6 days ago → 1 / (1 + 6) = 1/7 ≈ 0.1429
    six_days_ago = (datetime.now(tz=timezone.utc) - timedelta(days=6)).isoformat()
    score = recency_score(six_days_ago)
    assert score == pytest.approx(1 / 7, abs=0.01)


# ---------------------------------------------------------------------------
# score_video
# ---------------------------------------------------------------------------


def test_score_video_with_embedding_and_date():
    user_emb = [1.0, 0.0]
    video = {
        "id": "v1",
        "published_at": datetime.now(tz=timezone.utc).isoformat(),
        "embedding": [1.0, 0.0],  # identical → sim=1.0
    }
    score = score_video(video, user_emb)
    # recency≈1.0, sim=1.0 → composite ≈ 0.4*1 + 0.6*1 = 1.0
    assert score == pytest.approx(1.0, abs=0.01)


def test_score_video_missing_embedding():
    user_emb = [1.0, 0.0]
    video = {
        "id": "v2",
        "published_at": datetime.now(tz=timezone.utc).isoformat(),
        "embedding": None,
    }
    score = score_video(video, user_emb)
    # sim=0 → composite = 0.4 * recency + 0 ≈ 0.4
    assert 0.35 < score < 0.45


def test_score_video_missing_published_at():
    user_emb = [1.0, 0.0]
    video = {"id": "v3", "published_at": None, "embedding": [1.0, 0.0]}
    score = score_video(video, user_emb)
    # recency=0 → composite = 0 + 0.6*1 = 0.6
    assert score == pytest.approx(0.6, abs=0.01)


def test_score_video_negative_similarity_clamped():
    """Negative cosine similarity is clamped to 0 in score_video."""
    user_emb = [1.0, 0.0]
    video = {
        "id": "v4",
        "published_at": datetime.now(tz=timezone.utc).isoformat(),
        "embedding": [-1.0, 0.0],  # opposite → sim=-1, clamped to 0
    }
    score = score_video(video, user_emb)
    # Only recency contributes ≈ 0.4
    assert 0.35 < score < 0.45


# ---------------------------------------------------------------------------
# rank_and_select
# ---------------------------------------------------------------------------


def test_rank_and_select_empty():
    assert rank_and_select([], [1.0, 0.0]) == []


def test_rank_and_select_returns_top_n():
    now = datetime.now(tz=timezone.utc)
    videos = [
        {"id": str(i), "published_at": (now - timedelta(days=i)).isoformat(), "embedding": [float(i), 0.0]}
        for i in range(10)
    ]
    user_emb = [0.0, 0.0]  # zero → similarity=0, rank purely by recency
    selected = rank_and_select(videos, user_emb, top_n=3)
    assert len(selected) == 3


def test_rank_and_select_orders_by_score():
    now = datetime.now(tz=timezone.utc)
    high_score = {
        "id": "best",
        "published_at": now.isoformat(),        # very recent
        "embedding": [1.0, 0.0],
    }
    low_score = {
        "id": "worst",
        "published_at": "2000-01-01T00:00:00Z",  # very old
        "embedding": [-1.0, 0.0],
    }
    user_emb = [1.0, 0.0]
    selected = rank_and_select([low_score, high_score], user_emb, top_n=2)
    assert selected[0]["id"] == "best"


def test_rank_and_select_top_n_larger_than_list():
    videos = [{"id": "v1", "published_at": "2024-01-01T00:00:00Z", "embedding": [1.0]}]
    selected = rank_and_select(videos, [1.0], top_n=10)
    assert len(selected) == 1
