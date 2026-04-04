"""
Unit tests for extract_video_id() in services/youtube_ingestion.py.

No external dependencies — no YouTube API calls are made.
"""

from __future__ import annotations

import pytest

from services.youtube_ingestion import extract_video_id


# ---------------------------------------------------------------------------
# Valid URL formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected_id",
    [
        # Standard watch URL
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Without www
        ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # With extra query parameters
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123", "dQw4w9WgXcQ"),
        # Short URL
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Short URL with query params
        ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
        # Shorts
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Embed
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # /v/ path
        ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Privacy-enhanced embed
        ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Bare video ID (11 chars, no URL)
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # ID with underscores and hyphens (valid chars, exactly 11)
        ("abc_DEF-123", "abc_DEF-123"),
    ],
)
def test_extract_video_id_valid(url: str, expected_id: str):
    assert extract_video_id(url) == expected_id


def test_extract_video_id_strips_whitespace():
    assert extract_video_id("  dQw4w9WgXcQ  ") == "dQw4w9WgXcQ"


# ---------------------------------------------------------------------------
# Invalid inputs → ValueError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://www.youtube.com/watch",           # no v= param
        "https://www.youtube.com/channel/UC123",   # channel URL, not video
        "https://example.com/watch?v=dQw4w9WgXcQ", # wrong domain
        "not-a-url",                               # random string (not 11 chars)
        "",                                        # empty string
        "short",                                   # too short
        "ThisIsTooLongToBeAVideoID_12345",         # too long
        "https://youtu.be/",                       # youtu.be with no id
    ],
)
def test_extract_video_id_invalid_raises(bad_url: str):
    with pytest.raises(ValueError):
        extract_video_id(bad_url)
