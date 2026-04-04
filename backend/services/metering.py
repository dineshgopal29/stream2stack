"""
Metering service — records every AI/API usage event to the database.

Design:
  - record_sync()  — called from sync service code (thread-safe, non-blocking).
                     Appends to an in-process deque.
  - _drain_loop()  — async background coroutine started at app startup.
                     Flushes the deque to `usage_events` and updates
                     `quota_ledger` every DRAIN_INTERVAL_SECONDS.

This keeps metering completely off the hot path: callers never wait for DB I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid

logger = logging.getLogger(__name__)

DRAIN_INTERVAL_SECONDS: float = 5.0
DRAIN_BATCH_SIZE: int = 100

# ---------------------------------------------------------------------------
# UsageEvent data class
# ---------------------------------------------------------------------------


@dataclass
class UsageEvent:
    """Represents a single metered operation."""

    user_id: str
    # 'llm_call' | 'embedding' | 'scrape' | 'email' | 'ingest'
    event_type: str
    # 'concept_extraction' | 'blog_generation' | 'newsletter_assembly' |
    # 'embed_video' | 'scrape_url' | 'email_send' | 'video_ingest'
    operation: str
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    resource_id: Optional[str] = None      # newsletter_id or video_id (UUID str)
    org_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# In-process queue (deque is thread-safe for append / popleft)
# ---------------------------------------------------------------------------

_queue: deque[UsageEvent] = deque()


def record_sync(event: UsageEvent) -> None:
    """Enqueue a usage event from synchronous (or threaded) code.

    Non-blocking. The drain loop persists it to the database asynchronously.
    """
    _queue.append(event)


# ---------------------------------------------------------------------------
# Background drain loop
# ---------------------------------------------------------------------------


async def start_drain_loop() -> None:
    """Start the background drain coroutine. Call once from app lifespan."""
    asyncio.create_task(_drain_loop(), name="metering-drain")
    logger.info("Metering drain loop started (interval=%ss).", DRAIN_INTERVAL_SECONDS)


async def _drain_loop() -> None:
    """Continuously drain the queue to the database."""
    while True:
        try:
            await asyncio.sleep(DRAIN_INTERVAL_SECONDS)
            await _flush()
        except asyncio.CancelledError:
            # Flush remaining events before shutdown
            await _flush()
            raise
        except Exception as exc:
            logger.error("Metering drain error: %s", exc)


async def _flush() -> None:
    """Pop up to DRAIN_BATCH_SIZE events and persist them."""
    if not _queue:
        return

    batch: list[UsageEvent] = []
    while _queue and len(batch) < DRAIN_BATCH_SIZE:
        batch.append(_queue.popleft())

    if not batch:
        return

    try:
        await asyncio.to_thread(_write_events, batch)
        logger.debug("Metering: flushed %d events.", len(batch))
    except Exception as exc:
        logger.error("Metering: DB flush failed — %d events lost: %s", len(batch), exc)


def _write_events(events: list[UsageEvent]) -> None:
    """Persist events to `usage_events` and update `quota_ledger` (sync, runs in thread)."""
    from db.supabase_client import get_supabase_client
    supabase = get_supabase_client()

    # --- Insert usage_events ---
    rows = []
    for e in events:
        row = {
            "id":            e.id,
            "user_id":       e.user_id,
            "event_type":    e.event_type,
            "operation":     e.operation,
            "model":         e.model,
            "input_tokens":  e.input_tokens,
            "output_tokens": e.output_tokens,
            "cost_usd":      float(e.cost_usd) if e.cost_usd is not None else None,
            "resource_id":   e.resource_id,
            "org_id":        e.org_id,
            "metadata":      json.dumps(e.metadata) if e.metadata else "{}",
            "created_at":    e.created_at.isoformat(),
        }
        rows.append(row)

    supabase.table("usage_events").insert(rows).execute()

    # --- Update quota_ledger per user per period ---
    # Group by (user_id, period_start)
    from collections import defaultdict
    period_map: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "newsletters_used": 0,
        "videos_ingested":  0,
        "emails_sent":      0,
        "scrapes_used":     0,
        "llm_tokens_used":  0,
        "cost_usd_accrued": 0.0,
    })

    for e in events:
        period_start = e.created_at.strftime("%Y-%m-01")
        key = (e.user_id, period_start)
        bucket = period_map[key]

        if e.event_type == "llm_call":
            bucket["llm_tokens_used"] += (e.input_tokens or 0) + (e.output_tokens or 0)
        elif e.event_type == "embedding":
            bucket["llm_tokens_used"] += (e.input_tokens or 0)
        elif e.event_type == "email":
            bucket["emails_sent"] += 1
        elif e.event_type == "scrape":
            bucket["scrapes_used"] += 1
        elif e.event_type == "ingest":
            bucket["videos_ingested"] += 1

        if e.operation == "newsletter_assembly":
            bucket["newsletters_used"] += 1

        bucket["cost_usd_accrued"] += e.cost_usd or 0.0

    for (user_id, period_start), deltas in period_map.items():
        supabase.rpc(
            "upsert_quota_ledger",
            {
                "p_user_id":           user_id,
                "p_period_start":      period_start,
                "p_newsletters_delta": deltas["newsletters_used"],
                "p_videos_delta":      deltas["videos_ingested"],
                "p_emails_delta":      deltas["emails_sent"],
                "p_scrapes_delta":     deltas["scrapes_used"],
                "p_tokens_delta":      deltas["llm_tokens_used"],
                "p_cost_delta":        deltas["cost_usd_accrued"],
            },
        ).execute()
