"""
Markdown export service.

Formats newsletter content with YAML frontmatter and uploads it to a
Supabase Storage bucket for permanent, publicly-accessible hosting.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

_STORAGE_BUCKET = "newsletters"


def generate_markdown(
    newsletter_title: str,
    content_md: str,
    created_at: str,
) -> str:
    """Produce a Markdown document with YAML frontmatter.

    Args:
        newsletter_title: Title of the newsletter edition.
        content_md: The main Markdown body of the newsletter.
        created_at: ISO-8601 creation timestamp (used in frontmatter).

    Returns:
        Full Markdown string including frontmatter block.
    """
    # Normalise the date for human-readable frontmatter.
    try:
        if created_at.endswith("Z"):
            created_at_norm = created_at[:-1] + "+00:00"
        else:
            created_at_norm = created_at
        dt = datetime.fromisoformat(created_at_norm)
        date_str = dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Escape double-quotes in the title for safe YAML embedding.
    safe_title = newsletter_title.replace('"', '\\"')

    frontmatter = (
        "---\n"
        f'title: "{safe_title}"\n'
        f"date: {date_str}\n"
        f"generated_at: {created_at}\n"
        "---\n\n"
    )

    return frontmatter + content_md


def save_to_storage(newsletter_id: str, markdown: str) -> str:
    """Upload a Markdown newsletter to Supabase Storage and return its public URL.

    The file is stored at `newsletters/<newsletter_id>.md` inside the
    `newsletters` bucket.

    Args:
        newsletter_id: UUID of the newsletter (used as filename).
        markdown: The full Markdown content to upload.

    Returns:
        Public URL of the uploaded file.

    Raises:
        Exception: On upload or URL-generation failure.
    """
    supabase = get_supabase_client()

    file_path = f"{newsletter_id}.md"
    file_bytes = markdown.encode("utf-8")

    logger.info(
        "Uploading newsletter %s to storage bucket '%s'.",
        newsletter_id,
        _STORAGE_BUCKET,
    )

    try:
        supabase.storage.from_(_STORAGE_BUCKET).upload(
            path=file_path,
            file=file_bytes,
            file_options={"content-type": "text/markdown; charset=utf-8", "upsert": "true"},
        )
    except Exception as exc:
        logger.error("Storage upload failed for newsletter %s: %s", newsletter_id, exc)
        raise

    try:
        url_response = supabase.storage.from_(_STORAGE_BUCKET).get_public_url(file_path)
        # supabase-py returns the URL directly as a string; local stub returns file:// path.
        public_url: str = url_response if isinstance(url_response, str) else url_response.get("publicUrl", "")
        logger.info("Newsletter %s available at: %s", newsletter_id, public_url)
        return public_url
    except Exception as exc:
        logger.error("Failed to retrieve public URL for newsletter %s: %s", newsletter_id, exc)
        raise
