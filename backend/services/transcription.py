"""
Transcript fetching and storage service.

Uses the youtube_transcript_api library to retrieve auto-generated or
manually uploaded transcripts, then persists them in the `videos.transcript`
column in Supabase.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# v1.x: YouTubeTranscriptApi is now instantiated, not used as a static class.
_yt_api = YouTubeTranscriptApi()

# Matches auto-caption non-speech artifacts like [Music], [Applause], [Laughter], etc.
_ARTIFACT_RE = re.compile(r"\[[^\]]{1,40}\]")
# Collapse runs of whitespace to single space
_MULTI_SPACE_RE = re.compile(r" {2,}")

_PARAGRAPH_WORDS = 60  # target paragraph size


def _build_transcript(snippets) -> str:
    """Build clean, paragraph-structured transcript from caption snippets.

    - Decodes HTML entities (&#39; → ', &amp; → &, etc.)
    - Removes non-speech artifacts ([Music], [Applause], [Laughter], etc.)
    - Groups words into readable paragraphs (~60 words each)
    """
    words: list[str] = []
    for s in snippets:
        text = html.unescape(s.text.strip())
        text = _ARTIFACT_RE.sub("", text)
        text = _MULTI_SPACE_RE.sub(" ", text).strip()
        if text:
            words.extend(text.split())

    if not words:
        return ""

    paragraphs: list[str] = []
    for i in range(0, len(words), _PARAGRAPH_WORDS):
        para = " ".join(words[i : i + _PARAGRAPH_WORDS])
        paragraphs.append(para)

    return "\n\n".join(paragraphs)


def get_transcript(youtube_id: str) -> str:
    """Fetch the transcript for a YouTube video and return it as plain text.

    Tries English first, then falls back to any available language.
    Raises no exception on failure — returns an empty string instead so
    callers can decide how to handle missing transcripts.

    Args:
        youtube_id: 11-character YouTube video ID.

    Returns:
        The full transcript as a single string with sentences separated by spaces.
        Returns an empty string if no transcript is available.
    """
    try:
        transcript_list = _yt_api.list(youtube_id)

        # Prefer manually-created English, then generated English, then any language.
        try:
            transcript = transcript_list.find_manually_created_transcript(["en", "en-US", "en-GB"])
        except NoTranscriptFound:
            try:
                transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
            except NoTranscriptFound:
                # Last resort: take whatever is available and translate to English.
                available = list(transcript_list)
                if not available:
                    logger.warning("No transcripts available for video %s.", youtube_id)
                    return ""
                transcript = available[0]
                try:
                    transcript = transcript.translate("en")
                except Exception as exc:
                    logger.warning(
                        "Could not translate transcript for %s: %s. Using original.",
                        youtube_id,
                        exc,
                    )

        # v1.x: fetch() returns FetchedTranscript; snippets are objects with .text
        fetched = transcript.fetch()
        full_text = _build_transcript(fetched.snippets)
        logger.info(
            "Fetched transcript for %s: %d characters.", youtube_id, len(full_text)
        )
        return full_text

    except TranscriptsDisabled:
        logger.warning("Transcripts are disabled for video %s.", youtube_id)
        return ""
    except VideoUnavailable:
        logger.warning("Video %s is unavailable.", youtube_id)
        return ""
    except Exception as exc:
        logger.error("Unexpected error fetching transcript for %s: %s", youtube_id, exc)
        return ""


def fetch_and_store_transcript(video_id: str, youtube_id: str) -> str:
    """Retrieve a video's transcript and store it in the database.

    If the transcript already exists in the DB it is returned immediately
    without making an API call.

    Args:
        video_id: The UUID primary key of the row in the `videos` table.
        youtube_id: The 11-character YouTube video ID.

    Returns:
        The transcript text (may be empty if unavailable).
    """
    supabase = get_supabase_client()

    # Check whether we already have a transcript stored.
    try:
        result = (
            supabase.table("videos")
            .select("transcript")
            .eq("id", video_id)
            .single()
            .execute()
        )
        existing_transcript: str | None = result.data.get("transcript") if result.data else None
        if existing_transcript:
            logger.info("Transcript for video %s already in DB. Skipping fetch.", video_id)
            return existing_transcript
    except Exception as exc:
        logger.warning("Could not check existing transcript for video %s: %s", video_id, exc)

    # Fetch from YouTube.
    transcript_text = get_transcript(youtube_id)

    if not transcript_text:
        logger.warning("No transcript obtained for video %s (%s).", video_id, youtube_id)
        return ""

    # Persist to the database.
    try:
        supabase.table("videos").update({"transcript": transcript_text}).eq(
            "id", video_id
        ).execute()
        logger.info("Stored transcript for video %s (%d chars).", video_id, len(transcript_text))
    except Exception as exc:
        logger.error("Failed to store transcript for video %s: %s", video_id, exc)

    return transcript_text
