"""Unit tests for services/prompt_config.py."""

import importlib
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import services.prompt_config as pc


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear lru_cache before every test so state doesn't bleed."""
    pc.load_blog_system_prompt.cache_clear()
    yield
    pc.load_blog_system_prompt.cache_clear()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_load_prompt_extracts_between_markers(tmp_path, monkeypatch):
    prompt_file = tmp_path / "blog_system_prompt.md"
    prompt_file.write_text(
        "# Header comment\n\n"
        "---PROMPT_START---\n\n"
        "You are a writer.\n\n"
        "---PROMPT_END---\n\n"
        "# Trailing comment\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pc, "_PROMPT_FILE", prompt_file)
    result = pc.load_blog_system_prompt()
    assert result == "You are a writer."


def test_load_prompt_strips_whitespace(tmp_path, monkeypatch):
    prompt_file = tmp_path / "blog_system_prompt.md"
    prompt_file.write_text(
        "---PROMPT_START---\n\n   lots of whitespace   \n\n---PROMPT_END---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pc, "_PROMPT_FILE", prompt_file)
    assert pc.load_blog_system_prompt() == "lots of whitespace"


def test_load_prompt_is_cached(tmp_path, monkeypatch):
    prompt_file = tmp_path / "blog_system_prompt.md"
    prompt_file.write_text(
        "---PROMPT_START---\nOriginal.\n---PROMPT_END---\n", encoding="utf-8"
    )
    monkeypatch.setattr(pc, "_PROMPT_FILE", prompt_file)

    first = pc.load_blog_system_prompt()
    # Mutate the file — cached result should NOT change.
    prompt_file.write_text(
        "---PROMPT_START---\nModified.\n---PROMPT_END---\n", encoding="utf-8"
    )
    second = pc.load_blog_system_prompt()
    assert first == second == "Original."


def test_reload_clears_cache(tmp_path, monkeypatch):
    prompt_file = tmp_path / "blog_system_prompt.md"
    prompt_file.write_text(
        "---PROMPT_START---\nOriginal.\n---PROMPT_END---\n", encoding="utf-8"
    )
    monkeypatch.setattr(pc, "_PROMPT_FILE", prompt_file)
    pc.load_blog_system_prompt()

    prompt_file.write_text(
        "---PROMPT_START---\nUpdated.\n---PROMPT_END---\n", encoding="utf-8"
    )
    result = pc.reload_blog_system_prompt()
    assert result == "Updated."


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------

def test_fallback_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "_PROMPT_FILE", tmp_path / "nonexistent.md")
    result = pc.load_blog_system_prompt()
    assert result == pc._FALLBACK_PROMPT
    assert len(result) > 50  # fallback is non-trivial


def test_fallback_when_markers_missing(tmp_path, monkeypatch):
    prompt_file = tmp_path / "blog_system_prompt.md"
    prompt_file.write_text("No markers here at all.\n", encoding="utf-8")
    monkeypatch.setattr(pc, "_PROMPT_FILE", prompt_file)
    assert pc.load_blog_system_prompt() == pc._FALLBACK_PROMPT


def test_fallback_when_prompt_empty(tmp_path, monkeypatch):
    prompt_file = tmp_path / "blog_system_prompt.md"
    prompt_file.write_text(
        "---PROMPT_START---\n   \n---PROMPT_END---\n", encoding="utf-8"
    )
    monkeypatch.setattr(pc, "_PROMPT_FILE", prompt_file)
    assert pc.load_blog_system_prompt() == pc._FALLBACK_PROMPT


def test_fallback_when_end_before_start(tmp_path, monkeypatch):
    prompt_file = tmp_path / "blog_system_prompt.md"
    prompt_file.write_text(
        "---PROMPT_END---\nSome text.\n---PROMPT_START---\n", encoding="utf-8"
    )
    monkeypatch.setattr(pc, "_PROMPT_FILE", prompt_file)
    assert pc.load_blog_system_prompt() == pc._FALLBACK_PROMPT


# ---------------------------------------------------------------------------
# Guardrail content checks (real file)
# ---------------------------------------------------------------------------

def test_real_prompt_file_loads():
    """The actual prompt file ships with the repo and must parse correctly."""
    pc.load_blog_system_prompt.cache_clear()
    result = pc.load_blog_system_prompt()
    assert len(result) > 200, "Real prompt should be substantial"


def test_real_prompt_contains_injection_guardrail():
    pc.load_blog_system_prompt.cache_clear()
    result = pc.load_blog_system_prompt()
    keywords = ["forget", "ignore", "adversarial", "injection", "override"]
    assert any(k in result.lower() for k in keywords), (
        "Prompt must contain prompt-injection guardrail language"
    )


def test_real_prompt_contains_model_disclosure_guardrail():
    pc.load_blog_system_prompt.cache_clear()
    result = pc.load_blog_system_prompt()
    assert "model" in result.lower() or "vendor" in result.lower(), (
        "Prompt must contain model-disclosure guardrail"
    )
