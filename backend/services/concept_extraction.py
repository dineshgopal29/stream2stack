"""
Concept extraction service.

Uses an LLM to analyse a video transcript and extract structured technical
concepts, tools, patterns, and code hints.

- Production: Anthropic Claude (claude-sonnet-4-6) via ANTHROPIC_API_KEY
- Local dev:  Ollama via OLLAMA_BASE_URL (OpenAI-compatible API)
"""

from __future__ import annotations

import json
import logging
import os
import re

from dotenv import load_dotenv

from models.schemas import ConceptExtractionResult
from services.cost_rates import compute_token_cost
from services.metering import UsageEvent, record_sync

load_dotenv()

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior software engineer and technical writer. Your job is to analyse
the transcript of a technical YouTube video and extract structured information
that will be used to generate a developer-focused newsletter.

Always respond with ONLY valid JSON — no markdown fences, no explanatory text.
The JSON must match this schema exactly:

{
  "concepts": ["<concept1>", ...],
  "tools":    ["<tool1>", ...],
  "patterns": ["<pattern1>", ...],
  "code_hints": ["<code_hint1>", ...]
}

Definitions:
- concepts:   Core technical concepts explained in the video (e.g. "vector embeddings",
              "event-driven architecture", "RAG pipelines").
- tools:      Specific technologies, frameworks, libraries, cloud services, or CLIs
              mentioned (e.g. "LangChain", "Redis", "AWS Lambda", "dbt").
- patterns:   Architectural or design patterns discussed (e.g. "CQRS", "fan-out pattern",
              "strangler fig", "hexagonal architecture").
- code_hints: Concrete code-level details worth highlighting: API method names,
              SQL snippets, config keys, specific function signatures, data structure
              names (e.g. "pgvector <-> operator", "torch.nn.Embedding", "MERGE INTO").

Return between 3 and 10 items per list. Omit categories with zero relevant items
(use an empty list []). Prefer precision over quantity.
"""


def _max_transcript_chars() -> int:
    """Return transcript char limit based on the active LLM backend.

    Ollama local models typically have 8 192-token context windows.
    Budget: 8192 tokens - ~400 system - ~50 title - ~512 output ≈ 7 230 tokens
    @ ~4 chars/token → ~29 000 chars; use 12 000 as a conservative safe limit.

    Claude (200 K context) can comfortably handle 40 000 chars of transcript.
    """
    if os.getenv("OLLAMA_BASE_URL"):
        return 12_000
    return 40_000


def _build_user_prompt(title: str, transcript: str) -> str:
    max_chars = _max_transcript_chars()
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n\n[Transcript truncated for length]"

    return (
        f"Video title: {title}\n\n"
        f"Transcript:\n{transcript}"
    )


def _call_ollama(title: str, transcript: str, user_id: str = "unknown") -> str:
    """Call Ollama via the OpenAI-compatible API."""
    import openai

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_LLM_MODEL", "gemma4")

    client = openai.OpenAI(base_url=f"{base_url}/v1", api_key="ollama")
    response = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(title, transcript)},
        ],
    )
    in_tok  = getattr(getattr(response, "usage", None), "prompt_tokens", None)
    out_tok = getattr(getattr(response, "usage", None), "completion_tokens", None)
    record_sync(UsageEvent(
        user_id=user_id, event_type="llm_call", operation="concept_extraction",
        model=model, input_tokens=in_tok, output_tokens=out_tok,
        cost_usd=compute_token_cost(model, in_tok or 0, out_tok or 0),
    ))
    return response.choices[0].message.content.strip()


def _call_claude(title: str, transcript: str, user_id: str = "unknown") -> str:
    """Call Anthropic Claude."""
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")

    model = "claude-sonnet-4-6"
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(title, transcript)}],
    )
    record_sync(UsageEvent(
        user_id=user_id, event_type="llm_call", operation="concept_extraction",
        model=model,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        cost_usd=compute_token_cost(
            model, message.usage.input_tokens, message.usage.output_tokens
        ),
    ))
    return message.content[0].text.strip()


def extract_concepts(transcript: str, title: str, user_id: str = "unknown") -> ConceptExtractionResult:
    """Use an LLM to extract structured technical concepts from a transcript.

    Args:
        transcript: Full transcript text of the video.
        title: Video title (used as additional context for the model).

    Returns:
        A ConceptExtractionResult with concepts, tools, patterns, and code_hints.

    Raises:
        ValueError: If the model response cannot be parsed as valid JSON.
    """
    logger.info("Extracting concepts for video: %r", title)

    if os.getenv("OLLAMA_BASE_URL"):
        raw_response = _call_ollama(title, transcript, user_id)
    else:
        raw_response = _call_claude(title, transcript, user_id)

    logger.debug("Raw concept extraction response: %s", raw_response[:500])

    # Strip markdown code fences if the model ignores the system prompt instruction.
    raw_response = re.sub(r"^```(?:json)?\s*", "", raw_response, flags=re.IGNORECASE)
    raw_response = re.sub(r"\s*```$", "", raw_response.strip())

    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM response as JSON: %s\nRaw: %s", exc, raw_response)
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    result = ConceptExtractionResult(
        concepts=data.get("concepts", []),
        tools=data.get("tools", []),
        patterns=data.get("patterns", []),
        code_hints=data.get("code_hints", []),
    )

    logger.info(
        "Extracted %d concepts, %d tools, %d patterns, %d code_hints for %r.",
        len(result.concepts),
        len(result.tools),
        len(result.patterns),
        len(result.code_hints),
        title,
    )
    return result
