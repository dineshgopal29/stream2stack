"""
Blog and newsletter generation service.

Turns transcripts and extracted concepts into polished Markdown blog posts
and combined newsletter editions.

- Production: Anthropic Claude (claude-sonnet-4-6) via ANTHROPIC_API_KEY
- Local dev:  Ollama via OLLAMA_BASE_URL (OpenAI-compatible API)

Metering: every LLM call records a UsageEvent via services.metering.record_sync().
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv

from models.schemas import ConceptExtractionResult
from services.cost_rates import compute_token_cost
from services.metering import UsageEvent, record_sync
from services.prompt_config import load_blog_system_prompt
from services.wiki_context import get_relevant_pages, build_wiki_context_block, append_learn_more

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_NEWSLETTER_SYSTEM_PROMPT = """\
You are a seasoned technical newsletter editor. Your job is to combine multiple
individual video summaries into a single cohesive newsletter edition in Markdown.

The newsletter must follow this structure:

# <Newsletter Title>

> One-sentence edition tagline.

---

## This Week's Highlights

One-paragraph executive summary covering the common themes across all videos.

---

## Deep Dives

For each video summary provided, write a subsection:

### <Video Title>

- **TL;DR**: One sentence.
- **Key takeaways**: 3-5 bullet points.
- **Tools & Patterns**: Comma-separated list.

(Full blog post appended below the newsletter intro.)

---

## Parting Thought

One motivating or thought-provoking closing paragraph for developers.

Guidelines:
- Keep the newsletter intro (~500 words) tight and scannable.
- Derive the newsletter title from the common theme across videos.
- Do not invent information not present in the input.
- Respond with ONLY the Markdown content.
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int = 4_000) -> str:
    """Truncate text to stay within Ollama's effective context window."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[Content truncated for length]"


def _get_client():
    """Return (client, model, backend) tuple based on environment."""
    ollama_url = os.getenv("OLLAMA_BASE_URL")
    if ollama_url:
        import openai
        model = os.getenv("OLLAMA_LLM_MODEL", "gemma4")
        client = openai.OpenAI(base_url=f"{ollama_url}/v1", api_key="ollama")
        return client, model, "ollama"

    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")
    return anthropic.Anthropic(api_key=api_key), "claude-sonnet-4-6", "anthropic"


def _chat(
    client,
    model: str,
    backend: str,
    system: str,
    user: str,
    max_tokens: int,
    *,
    user_id: str = "unknown",
    operation: str = "unknown",
    resource_id: Optional[str] = None,
) -> str:
    """Unified LLM call. Records a UsageEvent after every successful call.

    Args:
        user_id:     Owner of the operation (for metering).
        operation:   Logical name, e.g. 'blog_generation' (for metering).
        resource_id: Optional newsletter/video UUID to link the event to.

    Returns:
        The model's text response with any wrapping code fences removed.
    """
    if backend == "ollama":
        ollama_max_tokens = min(max_tokens, 1024)
        response = client.chat.completions.create(
            model=model,
            max_tokens=ollama_max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content.strip()
        # Ollama OpenAI-compat API does return usage
        in_tok  = getattr(getattr(response, "usage", None), "prompt_tokens", None)
        out_tok = getattr(getattr(response, "usage", None), "completion_tokens", None)
    else:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        content = message.content[0].text.strip()
        in_tok  = message.usage.input_tokens
        out_tok = message.usage.output_tokens

    # Strip outer markdown fences that some models add despite instructions.
    content = re.sub(r"^```(?:markdown)?\s*\n?", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\n?```\s*$", "", content.strip())

    # Emit metering event (non-blocking — appended to in-process queue).
    cost = compute_token_cost(model, in_tok or 0, out_tok or 0)
    record_sync(UsageEvent(
        user_id=user_id,
        event_type="llm_call",
        operation=operation,
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        resource_id=resource_id,
    ))

    return content


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_blog(
    transcript: str,
    title: str,
    concepts: ConceptExtractionResult,
    description: Optional[str] = None,
    crawled_context: Optional[str] = None,
    *,
    user_id: str = "unknown",
    resource_id: Optional[str] = None,
) -> str:
    """Generate a full Markdown blog post for a single video.

    Args:
        transcript:      The video's full transcript text.
        title:           The video's title.
        concepts:        Structured concepts, tools, patterns, and code hints.
        description:     Optional user-provided intent/angle for the post.
        crawled_context: Optional pre-formatted block of crawled web content.
        user_id:         User who triggered this generation (for metering).
        resource_id:     Newsletter UUID to link the usage event to.

    Returns:
        Markdown-formatted blog post (without the title heading).
    """
    client, model, backend = _get_client()
    system_prompt = load_blog_system_prompt()

    concepts_block = (
        f"**Concepts**: {', '.join(concepts.concepts)}\n"
        f"**Tools**: {', '.join(concepts.tools)}\n"
        f"**Patterns**: {', '.join(concepts.patterns)}\n"
        f"**Code hints**: {', '.join(concepts.code_hints)}"
    )

    parts = [f"Video title: {title}\n"]

    if description:
        parts.append(
            f"## Author's Intent for This Post\n"
            f"{description}\n\n"
            f"Use this to shape the angle, depth, and focus of the post.\n"
        )

    parts.append(f"## Extracted Technical Metadata\n{concepts_block}\n")

    if crawled_context:
        parts.append(crawled_context)

    parts.append(f"## Video Transcript\n{_truncate(transcript)}")

    user_content = "\n\n".join(parts)

    # Wiki context injection — prepend relevant wiki pages to the user prompt.
    wiki_pages = get_relevant_pages(
        concepts=concepts.concepts,
        tools=concepts.tools,
        patterns=concepts.patterns,
    )
    if wiki_pages:
        wiki_block = build_wiki_context_block(wiki_pages)
        user_content = wiki_block + "\n\n" + user_content

    logger.info(
        "Generating blog post for: %r (user=%s, description=%s, crawled=%s, wiki_pages=%d)",
        title, user_id, bool(description), bool(crawled_context), len(wiki_pages),
    )
    blog_md = _chat(
        client, model, backend, system_prompt, user_content, max_tokens=4096,
        user_id=user_id, operation="blog_generation", resource_id=resource_id,
    )
    logger.info("Generated blog post for %r (%d chars).", title, len(blog_md))

    # Append Learn More section with wiki links.
    blog_md = append_learn_more(blog_md, wiki_pages)

    return blog_md


def generate_newsletter(
    videos_data: list[dict[str, Any]],
    *,
    user_id: str = "unknown",
    resource_id: Optional[str] = None,
) -> tuple[str, str]:
    """Combine multiple video blogs into a single newsletter edition.

    Args:
        videos_data: List of dicts, each containing title, transcript,
                     concepts (ConceptExtractionResult | dict), blog_md.
        user_id:     User who triggered this (for metering).
        resource_id: Newsletter UUID to link the usage event to.

    Returns:
        A tuple of (newsletter_title, combined_markdown).
    """
    if not videos_data:
        raise ValueError("videos_data must contain at least one video.")

    client, model, backend = _get_client()

    parts: list[str] = []
    for i, video in enumerate(videos_data, start=1):
        concepts = video.get("concepts")
        if isinstance(concepts, ConceptExtractionResult):
            tools_str    = ", ".join(concepts.tools)
            patterns_str = ", ".join(concepts.patterns)
        elif isinstance(concepts, dict):
            tools_str    = ", ".join(concepts.get("tools", []))
            patterns_str = ", ".join(concepts.get("patterns", []))
        else:
            tools_str = patterns_str = ""

        parts.append(
            f"--- Video {i} ---\n"
            f"Title: {video.get('title', 'Untitled')}\n"
            f"Tools: {tools_str}\n"
            f"Patterns: {patterns_str}\n\n"
            f"Blog post:\n{_truncate(video.get('blog_md', ''), max_chars=10_000)}\n"
        )

    user_content = "\n\n".join(parts)

    logger.info("Generating newsletter from %d videos (user=%s).", len(videos_data), user_id)
    combined_md = _chat(
        client, model, backend, _NEWSLETTER_SYSTEM_PROMPT, user_content, max_tokens=4096,
        user_id=user_id, operation="newsletter_assembly", resource_id=resource_id,
    )

    # Extract the newsletter title from the first H1 heading.
    title_match = re.search(r"^#\s+(.+)$", combined_md, re.MULTILINE)
    newsletter_title = title_match.group(1).strip() if title_match else "Weekly Tech Newsletter"

    # Append individual blog posts after the newsletter intro.
    blog_appendix_parts = ["\n\n---\n\n## Full Blog Posts\n"]
    for video in videos_data:
        vt      = video.get("title", "Untitled")
        blog_md = video.get("blog_md", "")
        blog_appendix_parts.append(f"\n# {vt}\n\n{blog_md}\n\n---\n")

    full_markdown = combined_md + "\n".join(blog_appendix_parts)

    logger.info(
        "Newsletter generated: title=%r, total chars=%d", newsletter_title, len(full_markdown)
    )
    return newsletter_title, full_markdown
