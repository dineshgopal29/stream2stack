"""Unit tests for transcription._build_transcript."""
from services.transcription import _build_transcript


class _Snippet:
    def __init__(self, text: str):
        self.text = text


def _snips(*texts: str) -> list[_Snippet]:
    return [_Snippet(t) for t in texts]


def test_removes_music_artifact():
    result = _build_transcript(_snips("[Music]", "hello world"))
    assert "[Music]" not in result
    assert "hello" in result


def test_removes_applause_artifact():
    result = _build_transcript(_snips("[Applause]", "thank you"))
    assert "[Applause]" not in result
    assert "thank you" in result


def test_decodes_html_entities():
    result = _build_transcript(_snips("we&#39;re using &amp; here"))
    assert "we're" in result
    assert "&" in result
    assert "&#39;" not in result
    assert "&amp;" not in result


def test_empty_snippets_returns_empty():
    assert _build_transcript([]) == ""


def test_all_artifacts_returns_empty():
    result = _build_transcript(_snips("[Music]", "[Applause]", "[Laughter]"))
    assert result == ""


def test_creates_paragraphs_for_long_input():
    # 180 words → 3 paragraphs at 60 words each
    words = [f"word{i}" for i in range(180)]
    snips = [_Snippet(w) for w in words]
    result = _build_transcript(snips)
    assert result.count("\n\n") == 2  # 3 paragraphs → 2 separators


def test_single_snippet_no_paragraph_break():
    result = _build_transcript(_snips("hello world"))
    assert "\n\n" not in result


def test_strips_whitespace_from_snippets():
    result = _build_transcript(_snips("  leading  ", "  trailing  "))
    assert result == "leading trailing"
