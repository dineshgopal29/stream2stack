"""
API tests for /newsletters endpoints.

All external services (LLM, DB, email) are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_response(data):
    resp = MagicMock()
    resp.data = data
    return resp


# ---------------------------------------------------------------------------
# GET /newsletters
# ---------------------------------------------------------------------------


def test_list_newsletters_returns_200(client, mock_db, sample_newsletter):
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        _make_db_response([sample_newsletter])
    )

    response = client.get("/newsletters?user_id=user-1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["title"] == "Weekly Dev Digest"


def test_list_newsletters_empty_returns_empty_list(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        _make_db_response([])
    )

    response = client.get("/newsletters?user_id=user-1")
    assert response.status_code == 200
    assert response.json() == []


def test_list_newsletters_missing_user_id_returns_422(client):
    response = client.get("/newsletters")  # no user_id param
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /newsletters/{id}
# ---------------------------------------------------------------------------


def test_get_newsletter_returns_200(client, mock_db, sample_newsletter):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(sample_newsletter)
    )

    response = client.get("/newsletters/nl-uuid-1")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "nl-uuid-1"
    assert data["title"] == "Weekly Dev Digest"


def test_get_newsletter_not_found_returns_404(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(None)
    )

    response = client.get("/newsletters/does-not-exist")
    assert response.status_code == 404


def test_get_newsletter_db_error_returns_502(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = (
        Exception("DB is down")
    )

    response = client.get("/newsletters/nl-uuid-1")
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# POST /newsletters/{id}/send
# ---------------------------------------------------------------------------


def test_send_newsletter_returns_200(client, mock_db, sample_newsletter):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(sample_newsletter)
    )
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        _make_db_response([])
    )

    with patch(
        "api.routes.newsletters.email_svc.send_newsletter",
        return_value={"id": "resend-msg-id"},
    ):
        response = client.post(
            "/newsletters/nl-uuid-1/send",
            json={"recipient_email": "test@example.com"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["resend_id"] == "resend-msg-id"


def test_send_newsletter_invalid_email_returns_422(client):
    response = client.post(
        "/newsletters/nl-uuid-1/send",
        json={"recipient_email": "not-an-email"},
    )
    assert response.status_code == 422


def test_send_newsletter_not_found_returns_404(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(None)
    )

    response = client.post(
        "/newsletters/does-not-exist/send",
        json={"recipient_email": "test@example.com"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /newsletters/{id}
# ---------------------------------------------------------------------------


def test_delete_newsletter_returns_204(client, mock_db, sample_newsletter):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(sample_newsletter)
    )
    mock_db.table.return_value.delete.return_value.eq.return_value.execute.return_value = (
        _make_db_response([])
    )

    response = client.delete("/newsletters/nl-uuid-1")
    assert response.status_code == 204


def test_delete_newsletter_not_found_returns_404(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(None)
    )

    response = client.delete("/newsletters/does-not-exist")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /newsletters/generate — description & source_urls fields
# ---------------------------------------------------------------------------

_GENERATE_PATCHES = [
    "api.routes.newsletters.concept_svc.extract_concepts",
    "api.routes.newsletters.blog_svc.generate_blog",
    "api.routes.newsletters.blog_svc.generate_newsletter",
    "api.routes.newsletters.email_svc.markdown_to_html",
    "api.routes.newsletters.email_svc.send_newsletter",
    "api.routes.newsletters.embed_svc.get_embedding",
    "api.routes.newsletters.dedup_svc.is_processed",
    "api.routes.newsletters.dedup_svc.check_similarity_duplicate",
    "api.routes.newsletters.dedup_svc.mark_processed",
    "api.routes.newsletters.md_svc.generate_markdown",
    "api.routes.newsletters.md_svc.save_to_storage",
    "api.routes.newsletters.crawler_svc.crawl_urls",
    "api.routes.newsletters.crawler_svc.build_crawled_context_block",
]


def _apply_patches(patches: dict):
    """Return a context manager that applies all patches from a {target: mock} dict."""
    import contextlib
    from unittest.mock import patch as _patch

    stack = contextlib.ExitStack()
    for target, mock_obj in patches.items():
        stack.enter_context(_patch(target, mock_obj))
    return stack


def _setup_generate_mocks(mock_db, sample_video, sample_newsletter):
    """Wire up the minimum DB mocks for a successful generate call."""
    from unittest.mock import MagicMock
    # videos query (.not_ is a property, not a call)
    mock_db.table.return_value.select.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = (
        _make_db_response([sample_video])
    )
    # settings query (for user embedding)
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(None)
    )
    # newsletter insert
    mock_db.table.return_value.insert.return_value.execute.return_value = (
        _make_db_response([sample_newsletter])
    )
    # newsletter_videos insert + storage update
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        _make_db_response([])
    )


def test_generate_with_description_passes_it_to_blog_generator(
    client, mock_db, sample_video, sample_newsletter
):
    _setup_generate_mocks(mock_db, sample_video, sample_newsletter)

    from unittest.mock import MagicMock, patch, call
    from models.schemas import ConceptExtractionResult

    captured = {}

    def fake_generate_blog(transcript, title, concepts, description=None, crawled_context=None):
        captured["description"] = description
        return "# Blog post"

    patches = {p: MagicMock() for p in _GENERATE_PATCHES}
    patches["api.routes.newsletters.blog_svc.generate_blog"] = fake_generate_blog
    patches["api.routes.newsletters.concept_svc.extract_concepts"].return_value = ConceptExtractionResult()
    patches["api.routes.newsletters.blog_svc.generate_newsletter"].return_value = (
        "Test Newsletter", "# Newsletter"
    )
    patches["api.routes.newsletters.email_svc.markdown_to_html"].return_value = "<html/>"
    patches["api.routes.newsletters.dedup_svc.is_processed"].return_value = False
    patches["api.routes.newsletters.dedup_svc.check_similarity_duplicate"].return_value = False
    patches["api.routes.newsletters.md_svc.generate_markdown"].return_value = "# md"
    patches["api.routes.newsletters.md_svc.save_to_storage"].return_value = "file://x"

    with _apply_patches(patches):
        response = client.post(
            "/newsletters/generate",
            json={
                "user_id": "user-1",
                "auto_select": True,
                "description": "Focus on production pitfalls",
            },
        )

    assert response.status_code == 201
    assert captured.get("description") == "Focus on production pitfalls"


def test_generate_with_source_urls_calls_crawler(
    client, mock_db, sample_video, sample_newsletter
):
    _setup_generate_mocks(mock_db, sample_video, sample_newsletter)

    from unittest.mock import MagicMock, patch
    from models.schemas import ConceptExtractionResult

    patches = {p: MagicMock() for p in _GENERATE_PATCHES}
    patches["api.routes.newsletters.concept_svc.extract_concepts"].return_value = ConceptExtractionResult()
    patches["api.routes.newsletters.blog_svc.generate_blog"].return_value = "# Blog"
    patches["api.routes.newsletters.blog_svc.generate_newsletter"].return_value = (
        "Newsletter", "# NL"
    )
    patches["api.routes.newsletters.email_svc.markdown_to_html"].return_value = "<html/>"
    patches["api.routes.newsletters.dedup_svc.is_processed"].return_value = False
    patches["api.routes.newsletters.dedup_svc.check_similarity_duplicate"].return_value = False
    patches["api.routes.newsletters.md_svc.generate_markdown"].return_value = "# md"
    patches["api.routes.newsletters.md_svc.save_to_storage"].return_value = "file://x"
    patches["api.routes.newsletters.crawler_svc.crawl_urls"].return_value = {
        "https://example.com": "some content"
    }
    patches["api.routes.newsletters.crawler_svc.build_crawled_context_block"].return_value = (
        "## Supplementary content"
    )

    with _apply_patches(patches):
        response = client.post(
            "/newsletters/generate",
            json={
                "user_id": "user-1",
                "auto_select": True,
                "source_urls": ["https://example.com"],
            },
        )

    assert response.status_code == 201
    patches["api.routes.newsletters.crawler_svc.crawl_urls"].assert_called_once_with(
        ["https://example.com"]
    )


def test_generate_without_source_urls_skips_crawler(
    client, mock_db, sample_video, sample_newsletter
):
    _setup_generate_mocks(mock_db, sample_video, sample_newsletter)

    from unittest.mock import MagicMock, patch
    from models.schemas import ConceptExtractionResult

    patches = {p: MagicMock() for p in _GENERATE_PATCHES}
    patches["api.routes.newsletters.concept_svc.extract_concepts"].return_value = ConceptExtractionResult()
    patches["api.routes.newsletters.blog_svc.generate_blog"].return_value = "# Blog"
    patches["api.routes.newsletters.blog_svc.generate_newsletter"].return_value = (
        "Newsletter", "# NL"
    )
    patches["api.routes.newsletters.email_svc.markdown_to_html"].return_value = "<html/>"
    patches["api.routes.newsletters.dedup_svc.is_processed"].return_value = False
    patches["api.routes.newsletters.dedup_svc.check_similarity_duplicate"].return_value = False
    patches["api.routes.newsletters.md_svc.generate_markdown"].return_value = "# md"
    patches["api.routes.newsletters.md_svc.save_to_storage"].return_value = "file://x"

    with _apply_patches(patches):
        response = client.post(
            "/newsletters/generate",
            json={"user_id": "user-1", "auto_select": True},
        )

    assert response.status_code == 201
    patches["api.routes.newsletters.crawler_svc.crawl_urls"].assert_not_called()


def test_generate_crawler_failure_does_not_block_generation(
    client, mock_db, sample_video, sample_newsletter
):
    """If crawling fails entirely, generation continues without crawled context."""
    _setup_generate_mocks(mock_db, sample_video, sample_newsletter)

    from unittest.mock import MagicMock, patch
    from models.schemas import ConceptExtractionResult

    patches = {p: MagicMock() for p in _GENERATE_PATCHES}
    patches["api.routes.newsletters.concept_svc.extract_concepts"].return_value = ConceptExtractionResult()
    patches["api.routes.newsletters.blog_svc.generate_blog"].return_value = "# Blog"
    patches["api.routes.newsletters.blog_svc.generate_newsletter"].return_value = (
        "Newsletter", "# NL"
    )
    patches["api.routes.newsletters.email_svc.markdown_to_html"].return_value = "<html/>"
    patches["api.routes.newsletters.dedup_svc.is_processed"].return_value = False
    patches["api.routes.newsletters.dedup_svc.check_similarity_duplicate"].return_value = False
    patches["api.routes.newsletters.md_svc.generate_markdown"].return_value = "# md"
    patches["api.routes.newsletters.md_svc.save_to_storage"].return_value = "file://x"
    # Crawler raises an exception
    patches["api.routes.newsletters.crawler_svc.crawl_urls"].side_effect = Exception("Network down")

    with _apply_patches(patches):
        response = client.post(
            "/newsletters/generate",
            json={
                "user_id": "user-1",
                "auto_select": True,
                "source_urls": ["https://example.com"],
            },
        )

    # Should still succeed — crawler failure is non-fatal
    assert response.status_code == 201


def test_generate_recipient_email_now_optional(client, mock_db, sample_video, sample_newsletter):
    """recipient_email is optional — omitting it should not return 422."""
    _setup_generate_mocks(mock_db, sample_video, sample_newsletter)

    from unittest.mock import MagicMock, patch
    from models.schemas import ConceptExtractionResult

    patches = {p: MagicMock() for p in _GENERATE_PATCHES}
    patches["api.routes.newsletters.concept_svc.extract_concepts"].return_value = ConceptExtractionResult()
    patches["api.routes.newsletters.blog_svc.generate_blog"].return_value = "# Blog"
    patches["api.routes.newsletters.blog_svc.generate_newsletter"].return_value = (
        "Newsletter", "# NL"
    )
    patches["api.routes.newsletters.email_svc.markdown_to_html"].return_value = "<html/>"
    patches["api.routes.newsletters.dedup_svc.is_processed"].return_value = False
    patches["api.routes.newsletters.dedup_svc.check_similarity_duplicate"].return_value = False
    patches["api.routes.newsletters.md_svc.generate_markdown"].return_value = "# md"
    patches["api.routes.newsletters.md_svc.save_to_storage"].return_value = "file://x"

    with _apply_patches(patches):
        response = client.post(
            "/newsletters/generate",
            json={"user_id": "user-1", "auto_select": True},
            # No recipient_email
        )

    assert response.status_code == 201
    # Email should NOT have been called
    patches["api.routes.newsletters.email_svc.send_newsletter"].assert_not_called()
