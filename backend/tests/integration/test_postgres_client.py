"""
Integration tests for db/postgres_client.py.

Requires a running PostgreSQL instance with DATABASE_URL set.
Run with:  pytest tests/integration/ -v  (after docker compose up -d)

All tests clean up after themselves — they insert rows and then delete them,
or run inside a transaction that is rolled back.
"""

from __future__ import annotations

import os
import uuid

import pytest
import psycopg2

# Skip entire module if no DATABASE_URL is configured.
pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _skip_if_no_db():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — skipping integration tests")


@pytest.fixture(scope="module", autouse=True)
def require_database():
    _skip_if_no_db()


@pytest.fixture(scope="module")
def pg_client():
    from db.postgres_client import PostgresClient

    return PostgresClient(DATABASE_URL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_YOUTUBE_ID = f"test_{uuid.uuid4().hex[:6]}"  # unique per run


@pytest.fixture(autouse=True)
def cleanup_test_rows(pg_client):
    """Delete any test rows created during this test."""
    yield
    try:
        pg_client.table("videos").select("id").eq("youtube_id", TEST_YOUTUBE_ID).execute()
        # Best-effort delete via raw psycopg2 (no delete builder yet)
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "videos" WHERE youtube_id = %s', (TEST_YOUTUBE_ID,))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# INSERT → SELECT round-trip
# ---------------------------------------------------------------------------


def test_insert_and_select(pg_client):
    row = {
        "youtube_id": TEST_YOUTUBE_ID,
        "title": "Integration Test Video",
        "description": "Created by pytest",
        "channel_name": "TestChannel",
        "duration_seconds": 120,
    }
    insert_result = pg_client.table("videos").insert(row).execute()
    assert isinstance(insert_result.data, list)
    assert len(insert_result.data) == 1
    assert insert_result.data[0]["youtube_id"] == TEST_YOUTUBE_ID

    select_result = pg_client.table("videos").select("*").eq("youtube_id", TEST_YOUTUBE_ID).execute()
    assert len(select_result.data) == 1
    assert select_result.data[0]["title"] == "Integration Test Video"


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------


def test_update(pg_client):
    row = {
        "youtube_id": TEST_YOUTUBE_ID,
        "title": "Original Title",
        "description": "",
        "channel_name": "C",
        "duration_seconds": 60,
    }
    pg_client.table("videos").insert(row).execute()

    update_result = (
        pg_client.table("videos")
        .update({"title": "Updated Title"})
        .eq("youtube_id", TEST_YOUTUBE_ID)
        .execute()
    )
    assert update_result.data[0]["title"] == "Updated Title"


# ---------------------------------------------------------------------------
# UPSERT — single conflict column
# ---------------------------------------------------------------------------


def test_upsert_single_conflict_column(pg_client):
    row = {
        "youtube_id": TEST_YOUTUBE_ID,
        "title": "First Insert",
        "description": "",
        "channel_name": "C",
        "duration_seconds": 60,
    }
    pg_client.table("videos").upsert(row, on_conflict="youtube_id").execute()

    row["title"] = "Upserted Title"
    upsert_result = pg_client.table("videos").upsert(row, on_conflict="youtube_id").execute()
    assert upsert_result.data[0]["title"] == "Upserted Title"


# ---------------------------------------------------------------------------
# .single() returns None (not {}) when no rows match
# ---------------------------------------------------------------------------


def test_single_returns_none_when_no_rows(pg_client):
    result = (
        pg_client.table("videos")
        .select("*")
        .eq("youtube_id", "definitely-does-not-exist-zzz")
        .single()
        .execute()
    )
    assert result.data is None


# ---------------------------------------------------------------------------
# .not_.is_("col", "null") filter
# ---------------------------------------------------------------------------


def test_not_is_null_filter(pg_client):
    # Insert a row with and one without a transcript.
    row_with = {
        "youtube_id": TEST_YOUTUBE_ID,
        "title": "Has transcript",
        "description": "",
        "channel_name": "C",
        "duration_seconds": 60,
        "transcript": "some text",
    }
    pg_client.table("videos").insert(row_with).execute()

    result = (
        pg_client.table("videos")
        .select("youtube_id, transcript")
        .not_.is_("transcript", "null")
        .eq("youtube_id", TEST_YOUTUBE_ID)
        .execute()
    )
    assert len(result.data) == 1
    assert result.data[0]["youtube_id"] == TEST_YOUTUBE_ID


def test_not_flag_resets_after_is_(pg_client):
    """Bug 3 fix: _negate_next resets even for non-null values of is_()."""
    # Two chained filters where the second uses .is_() again should NOT negate.
    # This is a regression guard — just ensure no SQL error is raised.
    try:
        pg_client.table("videos").select("*").not_.is_("transcript", "null").is_(
            "transcript", "null"
        ).execute()
    except Exception as exc:
        pytest.fail(f"Unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# .in_() with empty list edge case
# ---------------------------------------------------------------------------


def test_in_empty_list(pg_client):
    """An empty IN list should return no rows without crashing."""
    result = pg_client.table("videos").select("*").in_("id", []).execute()
    assert isinstance(result.data, list)
