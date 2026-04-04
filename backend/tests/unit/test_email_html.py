"""
Unit tests for markdown_to_html() in services/email_service.py.

Verifies that the converter produces correct HTML structure for each
Markdown element we use in generated newsletters.
"""

from __future__ import annotations

import pytest

from services.email_service import markdown_to_html


def test_output_is_full_html_document():
    html = markdown_to_html("Hello")
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "</html>" in html
    assert "<body>" in html


def test_h1_heading():
    html = markdown_to_html("# My Title")
    assert "<h1>My Title</h1>" in html


def test_h2_heading():
    html = markdown_to_html("## Section")
    assert "<h2>Section</h2>" in html


def test_h3_heading():
    html = markdown_to_html("### Sub-section")
    assert "<h3>Sub-section</h3>" in html


def test_bold_text_asterisks():
    html = markdown_to_html("**bold text**")
    assert "<strong>bold text</strong>" in html


def test_bold_text_underscores():
    html = markdown_to_html("__bold text__")
    assert "<strong>bold text</strong>" in html


def test_italic_text():
    html = markdown_to_html("*italic text*")
    assert "<em>italic text</em>" in html


def test_inline_code():
    html = markdown_to_html("`my_function()`")
    assert "<code>my_function()</code>" in html


def test_fenced_code_block():
    md = "```python\nprint('hello')\n```"
    html = markdown_to_html(md)
    assert "<pre>" in html
    assert "<code" in html
    assert "print" in html


def test_fenced_code_block_language_class():
    md = "```python\npass\n```"
    html = markdown_to_html(md)
    assert 'class="language-python"' in html


def test_blockquote():
    html = markdown_to_html("> This is a quote")
    assert "<blockquote>" in html
    assert "This is a quote" in html


def test_horizontal_rule_dashes():
    html = markdown_to_html("---")
    assert "<hr>" in html


def test_link():
    html = markdown_to_html("[Click here](https://example.com)")
    assert '<a href="https://example.com">Click here</a>' in html


def test_yaml_frontmatter_stripped():
    md = "---\ntitle: My Newsletter\ndate: 2024-01-01\n---\n\n# Content"
    html = markdown_to_html(md)
    assert "title: My Newsletter" not in html
    assert "<h1>Content</h1>" in html


def test_html_entities_escaped():
    html = markdown_to_html("Use <div> and & for HTML")
    assert "&lt;div&gt;" in html
    assert "&amp;" in html


def test_heading_levels_distinct():
    md = "# H1\n## H2\n### H3"
    html = markdown_to_html(md)
    assert "<h1>H1</h1>" in html
    assert "<h2>H2</h2>" in html
    assert "<h3>H3</h3>" in html


def test_footer_present():
    html = markdown_to_html("content")
    assert "Stream2Stack" in html
