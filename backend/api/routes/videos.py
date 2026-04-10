"""
Video ingestion and retrieval routes.

POST /videos/ingest  — ingest one or more videos (individual URLs + optional playlist).
GET  /videos         — list all ingested videos with transcript status.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from db.supabase_client import get_supabase_client
from models.schemas import VideoIngestRequest, VideoIngestResponse
from urllib.parse import urlparse

from services import (
    embeddings as embeddings_svc,
    transcription as transcription_svc,
    youtube_ingestion as ingestion_svc,
    web_ingestion as web_svc,
)
from services import wiki_compiler as compiler_svc
from services.quota_gate import QuotaGate


def _is_youtube_url(url: str) -> bool:
    """Return True if url points to YouTube (youtube.com or youtu.be)."""
    host = urlparse(url.strip()).hostname or ""
    return "youtube.com" in host or "youtu.be" in host

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /videos/ingest
# ---------------------------------------------------------------------------


@router.post(
    "/ingest",
    response_model=VideoIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest YouTube videos",
    description=(
        "Fetches video metadata from the YouTube Data API, stores it in the database, "
        "retrieves transcripts, and generates semantic embeddings for each video."
    ),
)
async def ingest_videos(body: VideoIngestRequest) -> VideoIngestResponse:
    """Ingest videos from individual URLs and/or a playlist URL.

    Pipeline per video:
      1. Fetch YouTube metadata → store in `videos` table.
      2. Fetch transcript → store in `videos.transcript`.
      3. Generate OpenAI embedding → store in `videos.embedding`.
    """
    if not body.urls and not body.playlist_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one video URL or a playlist_url.",
        )

    # Quota gate — only enforced when user_id is provided.
    quota_headers: dict[str, str] = {}
    if body.user_id:
        quota_headers = await QuotaGate("videos").check(body.user_id)

    # Step 1: Split URLs by type, then ingest both YouTube and web sources.
    youtube_urls = [u for u in body.urls if _is_youtube_url(u)]
    web_urls     = [u for u in body.urls if not _is_youtube_url(u)]

    videos: list[dict[str, Any]] = []

    if youtube_urls or body.playlist_url:
        try:
            yt_videos = await asyncio.to_thread(
                ingestion_svc.ingest_videos,
                youtube_urls,
                body.playlist_url,
            )
            videos.extend(yt_videos)
        except Exception as exc:
            logger.exception("YouTube ingestion failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"YouTube API error during ingestion: {exc}",
            )

    for url in web_urls:
        try:
            web_video = await asyncio.to_thread(web_svc.ingest_web_url, url)
            videos.append(web_video)
        except Exception as exc:
            logger.warning("Web ingestion failed for %r: %s", url, exc)

    if not videos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid sources could be ingested from the provided URLs.",
        )

    # Steps 2 & 3: Transcript + embedding for each video (parallelised).
    async def process_single_video(video: dict[str, Any]) -> dict[str, Any]:
        video_id: str = video["id"]
        youtube_id: str = video["youtube_id"]

        # Transcript
        try:
            transcript = await asyncio.to_thread(
                transcription_svc.fetch_and_store_transcript,
                video_id,
                youtube_id,
            )
        except Exception as exc:
            logger.warning("Transcript fetch failed for video %s: %s", video_id, exc)
            transcript = ""

        # Embedding (requires transcript or falls back to title + description)
        embed_text = transcript or f"{video.get('title', '')} {video.get('description', '')}".strip()
        if embed_text:
            try:
                await asyncio.to_thread(
                    embeddings_svc.embed_and_store,
                    video_id, embed_text,
                    body.user_id or "unknown",
                )
                video["has_embedding"] = True
            except Exception as exc:
                logger.warning("Embedding failed for video %s: %s", video_id, exc)
                video["has_embedding"] = False

        video["has_transcript"] = bool(transcript)
        return video

    processed: list[dict[str, Any]] = await asyncio.gather(
        *[process_single_video(v) for v in videos], return_exceptions=False
    )

    # Fire-and-forget wiki compile so knowledge base stays fresh after every ingest.
    async def _compile_wiki_bg() -> None:
        try:
            await asyncio.to_thread(compiler_svc.compile_wiki, user_id="system")
            logger.info("Background wiki compile completed after ingest.")
        except Exception as exc:
            logger.warning("Background wiki compile failed: %s", exc)

    asyncio.create_task(_compile_wiki_bg())

    # For playlist ingests with more than 3 videos: narrow to the 3 most
    # thematically cohesive videos so the response (and generation) stays focused.
    if body.playlist_url and len(processed) > 3:
        from services.ranking import select_cohesive_top_n
        processed = select_cohesive_top_n(processed, n=3)
        logger.info(
            "Playlist ingest narrowed to %d cohesive videos.", len(processed)
        )

    return VideoIngestResponse(
        videos=processed,
        message=f"Successfully ingested {len(processed)} source(s).",
    )


# ---------------------------------------------------------------------------
# GET /videos
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List ingested videos",
    description="Returns all videos in the database with basic metadata and transcript/embedding status.",
)
async def list_videos() -> list[dict[str, Any]]:
    """Return all videos from the database, ordered by most recently ingested."""
    supabase = get_supabase_client()

    try:
        result = (
            supabase.table("videos")
            .select(
                "id, youtube_id, source_type, source_url, title, channel_name, published_at, "
                "duration_seconds, thumbnail_url, created_at, "
                "transcript, embedding"
            )
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to list videos: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Database error: {exc}",
        )

    videos = result.data or []

    # Summarise presence of transcript / embedding without sending raw data.
    for video in videos:
        video["has_transcript"] = bool(video.pop("transcript", None))
        video["has_embedding"] = bool(video.pop("embedding", None))

    return videos
