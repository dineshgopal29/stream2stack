"""
YouTube ingestion service.

Responsibilities:
- Parse video / playlist URLs into video IDs.
- Fetch video metadata via the YouTube Data API v3.
- Persist metadata into the Supabase `videos` table.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from db.supabase_client import get_supabase_client

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _build_youtube_client():
    """Return an authenticated YouTube Data API v3 resource."""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY environment variable is not set.")
    return build("youtube", "v3", developerKey=api_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_video_id(url: str) -> str:
    """Extract the 11-character YouTube video ID from various URL formats.

    Supported formats:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/embed/VIDEO_ID
      - https://www.youtube.com/shorts/VIDEO_ID
      - Raw video ID (11 chars, no protocol)

    Args:
        url: A YouTube URL or bare video ID.

    Returns:
        The 11-character video ID.

    Raises:
        ValueError: If a valid video ID cannot be extracted.
    """
    url = url.strip()

    # Already a raw video ID?
    if _YOUTUBE_ID_RE.match(url):
        return url

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # youtu.be/<id>
    if "youtu.be" in hostname:
        video_id = parsed.path.lstrip("/").split("?")[0].split("/")[0]
        if _YOUTUBE_ID_RE.match(video_id):
            return video_id

    # youtube.com paths: /watch, /embed, /shorts, /v/
    if "youtube.com" in hostname or "youtube-nocookie.com" in hostname:
        # /watch?v=...
        qs = parse_qs(parsed.query)
        if "v" in qs:
            video_id = qs["v"][0]
            if _YOUTUBE_ID_RE.match(video_id):
                return video_id

        # /embed/<id>, /shorts/<id>, /v/<id>
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2 and path_parts[0] in ("embed", "shorts", "v", "e"):
            video_id = path_parts[1]
            if _YOUTUBE_ID_RE.match(video_id):
                return video_id

    raise ValueError(f"Could not extract a YouTube video ID from URL: {url!r}")


def get_playlist_video_ids(playlist_url: str) -> list[str]:
    """Return all video IDs in a YouTube playlist.

    Args:
        playlist_url: Full YouTube playlist URL containing a `list=` parameter.

    Returns:
        Ordered list of video IDs.

    Raises:
        ValueError: If `list` parameter is missing.
        HttpError: On YouTube API errors.
    """
    parsed = urlparse(playlist_url)
    qs = parse_qs(parsed.query)
    if "list" not in qs:
        raise ValueError(f"No playlist ID found in URL: {playlist_url!r}")

    playlist_id = qs["list"][0]
    youtube = _build_youtube_client()

    video_ids: list[str] = []
    page_token: str | None = None

    while True:
        request_kwargs: dict[str, Any] = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            request_kwargs["pageToken"] = page_token

        response = youtube.playlistItems().list(**request_kwargs).execute()

        for item in response.get("items", []):
            vid_id = item["contentDetails"]["videoId"]
            video_ids.append(vid_id)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.info("Playlist %s contains %d videos.", playlist_id, len(video_ids))
    return video_ids


def _parse_iso8601_duration(duration: str) -> int:
    """Convert ISO 8601 duration string (e.g. PT1H2M3S) to total seconds."""
    pattern = re.compile(
        r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", re.IGNORECASE
    )
    match = pattern.fullmatch(duration)
    if not match:
        return 0
    days, hours, minutes, seconds = (int(v or 0) for v in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def fetch_video_metadata(video_id: str) -> dict[str, Any]:
    """Fetch a single video's metadata from the YouTube Data API.

    Args:
        video_id: 11-character YouTube video ID.

    Returns:
        Dict with keys: youtube_id, title, description, channel_name,
        published_at, duration_seconds, thumbnail_url.

    Raises:
        ValueError: If the video is not found.
        HttpError: On YouTube API errors.
    """
    youtube = _build_youtube_client()

    response = (
        youtube.videos()
        .list(part="snippet,contentDetails", id=video_id)
        .execute()
    )

    items = response.get("items", [])
    if not items:
        raise ValueError(f"Video not found: {video_id!r}")

    item = items[0]
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})

    thumbnails = snippet.get("thumbnails", {})
    thumbnail_url = (
        thumbnails.get("maxres", {}).get("url")
        or thumbnails.get("high", {}).get("url")
        or thumbnails.get("default", {}).get("url")
        or ""
    )

    duration_seconds = _parse_iso8601_duration(content_details.get("duration", ""))

    return {
        "youtube_id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "channel_name": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt"),
        "duration_seconds": duration_seconds,
        "thumbnail_url": thumbnail_url,
    }


def ingest_videos(
    urls: list[str],
    playlist_url: str | None = None,
) -> list[dict[str, Any]]:
    """Ingest videos from individual URLs and/or a playlist URL.

    Steps for each video:
      1. Extract video ID.
      2. Fetch metadata from YouTube API.
      3. Upsert into Supabase `videos` table (keyed on `youtube_id`).
      4. Return the full DB record (including auto-generated `id`).

    Args:
        urls: List of individual YouTube video URLs.
        playlist_url: Optional playlist URL to expand.

    Returns:
        List of video dicts as stored in the DB, each containing an `id` field.
    """
    supabase = get_supabase_client()

    # Collect all video IDs (deduplicated, preserving order)
    all_ids: list[str] = []
    seen: set[str] = set()

    for url in urls:
        try:
            vid_id = extract_video_id(url)
        except ValueError as exc:
            logger.warning("Skipping URL %r: %s", url, exc)
            continue
        if vid_id not in seen:
            seen.add(vid_id)
            all_ids.append(vid_id)

    if playlist_url:
        try:
            playlist_ids = get_playlist_video_ids(playlist_url)
            for vid_id in playlist_ids:
                if vid_id not in seen:
                    seen.add(vid_id)
                    all_ids.append(vid_id)
        except Exception as exc:
            logger.error("Failed to fetch playlist %r: %s", playlist_url, exc)

    if not all_ids:
        logger.warning("No valid video IDs resolved from input.")
        return []

    logger.info("Ingesting %d unique videos.", len(all_ids))
    ingested: list[dict[str, Any]] = []

    for vid_id in all_ids:
        try:
            metadata = fetch_video_metadata(vid_id)
        except Exception as exc:
            logger.error("Failed to fetch metadata for %s: %s", vid_id, exc)
            continue

        try:
            result = (
                supabase.table("videos")
                .upsert(metadata, on_conflict="youtube_id")
                .execute()
            )
            records = result.data
            if records:
                ingested.append(records[0])
                logger.info("Upserted video %s → DB id=%s", vid_id, records[0].get("id"))
            else:
                # Row already existed and was not returned by upsert; fetch it.
                existing = (
                    supabase.table("videos")
                    .select("*")
                    .eq("youtube_id", vid_id)
                    .single()
                    .execute()
                )
                if existing.data:
                    ingested.append(existing.data)
        except Exception as exc:
            logger.error("DB upsert failed for video %s: %s", vid_id, exc)

    return ingested
