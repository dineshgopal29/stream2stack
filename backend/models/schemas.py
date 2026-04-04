"""
Pydantic schemas for the Stream2Stack API.

All models use pydantic v2 conventions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ---------------------------------------------------------------------------
# YouTube / Video models
# ---------------------------------------------------------------------------


class VideoMetadata(BaseModel):
    """Parsed metadata from the YouTube Data API."""

    youtube_id: str = Field(..., description="The 11-character YouTube video ID.")
    title: str
    description: str = ""
    channel_name: str = ""
    published_at: Optional[str] = None  # ISO-8601 string as returned by YouTube API
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None

    model_config = {"from_attributes": True}


class VideoIngestRequest(BaseModel):
    """Request body for the /videos/ingest endpoint."""

    urls: list[str] = Field(default_factory=list, description="Individual YouTube video URLs.")
    playlist_url: Optional[str] = Field(
        None, description="Optional YouTube playlist URL to bulk-ingest."
    )
    user_id: Optional[str] = Field(
        None,
        description="User ID for quota tracking. If omitted, quota is not enforced.",
    )

    @field_validator("urls", mode="before")
    @classmethod
    def deduplicate_urls(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for url in v:
            if url not in seen:
                seen.add(url)
                result.append(url)
        return result


class VideoIngestResponse(BaseModel):
    """Response body for the /videos/ingest endpoint."""

    videos: list[dict[str, Any]] = Field(
        default_factory=list, description="List of ingested video records."
    )
    message: str = "Videos ingested successfully."


# ---------------------------------------------------------------------------
# Newsletter models
# ---------------------------------------------------------------------------


class NewsletterGenerateRequest(BaseModel):
    """Request body for POST /newsletters/generate."""

    user_id: str
    video_ids: Optional[list[str]] = Field(
        None,
        description="Explicit list of DB video UUIDs to include. "
        "Ignored when auto_select=True.",
    )
    auto_select: bool = Field(
        True, description="Automatically rank and select the best videos."
    )
    recipient_email: Optional[str] = Field(
        None,
        description="Email address to send the newsletter to. "
        "If omitted the newsletter is saved as a draft.",
    )
    description: Optional[str] = Field(
        None,
        description="User-provided intent or angle for the blog post "
        "(e.g. 'focus on production pitfalls', 'write for a beginner audience'). "
        "Used to shape the generated content.",
    )
    source_urls: Optional[list[str]] = Field(
        None,
        description=(
            "Additional URLs to enrich blog generation context. Accepts a mix of:\n"
            "  - YouTube video URLs (youtube.com/watch?v=..., youtu.be/..., shorts/...) "
            "— transcripts are fetched automatically.\n"
            "  - Regular web URLs (HTTP/HTTPS) — page content is extracted via Firecrawl."
        ),
    )
    force: bool = Field(
        False,
        description="Skip deduplication checks and regenerate even from already-processed videos.",
    )


class NewsletterResponse(BaseModel):
    """Serialized newsletter record returned to the caller."""

    id: str
    title: str
    content_md: str
    content_html: Optional[str] = None
    status: str = "draft"
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------


class UserSettings(BaseModel):
    """User preferences stored in the user_settings table."""

    user_id: str
    email_frequency: str = Field(
        "weekly",
        description="How often to send newsletters: 'daily', 'weekly', 'biweekly'.",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="List of technical topics the user is interested in.",
    )
    playlist_urls: list[str] = Field(
        default_factory=list,
        description="YouTube playlist URLs to monitor for new content.",
    )
    recipient_email: Optional[str] = Field(
        None, description="Override email for newsletter delivery."
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# AI extraction / generation models
# ---------------------------------------------------------------------------


class ConceptExtractionResult(BaseModel):
    """Structured output from the Claude concept-extraction prompt."""

    concepts: list[str] = Field(
        default_factory=list,
        description="Core technical concepts covered in the video.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Technologies, frameworks, and tools mentioned.",
    )
    patterns: list[str] = Field(
        default_factory=list,
        description="Architectural or design patterns discussed.",
    )
    code_hints: list[str] = Field(
        default_factory=list,
        description="Key code snippets, method names, or API calls referenced.",
    )
