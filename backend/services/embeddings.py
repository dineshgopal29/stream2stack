"""
Embedding generation service.

Generates semantic embeddings and stores them in the `videos.embedding` column.

- Production: OpenAI text-embedding-3-small (1536-dim) via OPENAI_API_KEY
- Local dev:  Ollama qwen3-embedding (1024-dim) via OLLAMA_BASE_URL
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

from db.supabase_client import get_supabase_client
from services.cost_rates import compute_token_cost
from services.metering import UsageEvent, record_sync

load_dotenv()

logger = logging.getLogger(__name__)

_OPENAI_MODEL = "text-embedding-3-small"
_OPENAI_DIMENSIONS = 1536

# Ollama's default context window is 2048 tokens (~8 192 chars at 4 chars/token).
# Truncating to 6 000 chars keeps us safely within that budget while still
# capturing the most topic-dense part of the transcript.
_MAX_EMBED_CHARS = 6_000


def _get_embedding_client() -> tuple[OpenAI, str, int]:
    """Return (client, model, dimensions) for the active embedding backend."""
    ollama_url = os.getenv("OLLAMA_BASE_URL")
    if ollama_url:
        model = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding")
        dimensions = int(os.getenv("OLLAMA_EMBED_DIMENSIONS", "1024"))
        client = OpenAI(base_url=f"{ollama_url}/v1", api_key="ollama")
        return client, model, dimensions

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set.")
    return OpenAI(api_key=api_key), _OPENAI_MODEL, _OPENAI_DIMENSIONS


def get_embedding(text: str, user_id: str = "unknown", resource_id: str | None = None) -> list[float]:
    """Generate a semantic embedding vector for the given text.

    Args:
        text:        Input text to embed.
        user_id:     Owner of the operation (for metering).
        resource_id: Optional video UUID to link the usage event to.

    Returns:
        A list of floats representing the embedding vector.
        Length is 1536 (OpenAI) or 1024 (Ollama qwen3-embedding) depending on env.

    Raises:
        ValueError: If text is empty or required env vars are missing.
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text.")

    client, model, is_ollama_dims = _get_embedding_client()

    # OpenAI recommends replacing newlines with spaces for embedding quality.
    clean_text = text.replace("\n", " ").strip()

    # Truncate to stay within Ollama's default context window.
    if len(clean_text) > _MAX_EMBED_CHARS:
        logger.debug("Truncating embed input from %d to %d chars.", len(clean_text), _MAX_EMBED_CHARS)
        clean_text = clean_text[:_MAX_EMBED_CHARS]

    if os.getenv("OLLAMA_BASE_URL"):
        response = client.embeddings.create(model=model, input=clean_text)
    else:
        response = client.embeddings.create(
            model=model, input=clean_text, dimensions=_OPENAI_DIMENSIONS
        )

    # Capture token usage — OpenAI returns usage on embedding responses.
    in_tok = getattr(getattr(response, "usage", None), "prompt_tokens", None)
    cost   = compute_token_cost(model, in_tok or 0, 0)
    record_sync(UsageEvent(
        user_id=user_id, event_type="embedding", operation="embed_video",
        model=model, input_tokens=in_tok, output_tokens=0,
        cost_usd=cost, resource_id=resource_id,
    ))

    vector = response.data[0].embedding
    logger.debug("Generated embedding with %d dimensions.", len(vector))
    return vector


def embed_and_store(video_id: str, text: str, user_id: str = "unknown") -> None:
    """Generate an embedding and persist it to the `videos.embedding` column.

    If an embedding already exists for the video it is overwritten (idempotent).

    Args:
        video_id: UUID primary key of the row in the `videos` table.
        text: Text to embed (typically the transcript, or title + description).

    Raises:
        ValueError: If text is empty or API keys are missing.
        Exception: On database write failure.
    """
    logger.info("Generating embedding for video %s.", video_id)

    vector = get_embedding(text, user_id=user_id, resource_id=video_id)

    supabase = get_supabase_client()
    try:
        supabase.table("videos").update({"embedding": vector}).eq("id", video_id).execute()
        logger.info("Stored embedding for video %s.", video_id)
    except Exception as exc:
        logger.error("Failed to store embedding for video %s: %s", video_id, exc)
        raise
