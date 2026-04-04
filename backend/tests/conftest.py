"""
Shared fixtures for the Stream2Stack test suite.

Provides:
  - sample_video / sample_newsletter: canonical test data dicts
  - mock_db: MagicMock with Supabase-style query chaining
  - client: FastAPI TestClient with all DB calls mocked out
"""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Make sure backend/ is importable regardless of where pytest is invoked from.
_BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_video() -> dict:
    return {
        "id": "vid-uuid-1",
        "youtube_id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "description": "A test video about Python.",
        "channel_name": "Test Channel",
        "published_at": "2024-01-15T10:00:00Z",
        "duration_seconds": 300,
        "thumbnail_url": "https://img.youtube.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
        "transcript": "This is a test transcript about Python and FastAPI.",
        "embedding": [0.1, 0.2, 0.3],
        "created_at": "2024-01-16T10:00:00Z",
    }


@pytest.fixture
def sample_newsletter() -> dict:
    return {
        "id": "nl-uuid-1",
        "title": "Weekly Dev Digest",
        "content_md": "# Weekly Dev Digest\n\nContent here.",
        "content_html": "<h1>Weekly Dev Digest</h1><p>Content here.</p>",
        "status": "draft",
        "user_id": "user-1",
        "created_at": "2024-01-17T10:00:00Z",
        "storage_url": "",
    }


# ---------------------------------------------------------------------------
# Mock DB
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> MagicMock:
    """MagicMock that supports Supabase-style query chaining.

    Configure per-test return values like:
        mock_db.table.return_value.select.return_value.execute.return_value.data = [...]
    """
    return MagicMock()


def _make_response(data):
    """Helper: build a mock _Response with .data set."""
    resp = MagicMock()
    resp.data = data
    return resp


# ---------------------------------------------------------------------------
# FastAPI TestClient (DB mocked)
# ---------------------------------------------------------------------------

# Modules that import get_supabase_client and call it inside route handlers.
_PATCH_TARGETS = [
    "api.routes.videos.get_supabase_client",
    "api.routes.newsletters.get_supabase_client",
    "api.routes.settings.get_supabase_client",
    "main.get_supabase_client",
]


@pytest.fixture
def client(mock_db: MagicMock) -> TestClient:
    """FastAPI TestClient with all DB calls redirected to mock_db."""
    with ExitStack() as stack:
        for target in _PATCH_TARGETS:
            stack.enter_context(patch(target, return_value=mock_db))

        # Import here so patches are in place for the lifespan startup check.
        from main import create_app

        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc
