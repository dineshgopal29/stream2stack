"""
API tests for /videos endpoints.

All external services (YouTube API, transcription, embeddings, DB) are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# POST /videos/ingest
# ---------------------------------------------------------------------------


def test_ingest_no_urls_returns_422(client):
    response = client.post("/videos/ingest", json={"urls": [], "playlist_url": None})
    assert response.status_code == 422


def test_ingest_with_valid_url_returns_201(client, sample_video):
    with (
        patch(
            "api.routes.videos.ingestion_svc.ingest_videos",
            return_value=[sample_video],
        ),
        patch(
            "api.routes.videos.transcription_svc.fetch_and_store_transcript",
            return_value="transcript text",
        ),
        patch("api.routes.videos.embeddings_svc.embed_and_store", return_value=None),
    ):
        response = client.post(
            "/videos/ingest",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
        )

    assert response.status_code == 201
    data = response.json()
    assert "videos" in data
    assert data["videos"][0]["youtube_id"] == "dQw4w9WgXcQ"
    assert data["videos"][0]["has_transcript"] is True
    assert data["videos"][0]["has_embedding"] is True


def test_ingest_youtube_api_error_returns_502(client):
    with patch(
        "api.routes.videos.ingestion_svc.ingest_videos",
        side_effect=Exception("YouTube API quota exceeded"),
    ):
        response = client.post(
            "/videos/ingest",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
        )
    assert response.status_code == 502


def test_ingest_no_valid_videos_returns_422(client):
    with patch(
        "api.routes.videos.ingestion_svc.ingest_videos",
        return_value=[],  # ingest returned nothing
    ):
        response = client.post(
            "/videos/ingest",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
        )
    assert response.status_code == 422
    assert "No valid sources" in response.json()["detail"]


def test_ingest_missing_body_returns_422(client):
    response = client.post("/videos/ingest", json={})
    # No urls and no playlist_url → 422
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /videos
# ---------------------------------------------------------------------------


def test_list_videos_returns_200(client, mock_db, sample_video):
    resp_mock = MagicMock()
    resp_mock.data = [sample_video]
    mock_db.table.return_value.select.return_value.order.return_value.execute.return_value = (
        resp_mock
    )

    response = client.get("/videos")
    assert response.status_code == 200
    videos = response.json()
    assert isinstance(videos, list)
    assert len(videos) == 1
    assert "has_transcript" in videos[0]
    assert "has_embedding" in videos[0]
    # Raw transcript and embedding should NOT be in the response
    assert "transcript" not in videos[0]
    assert "embedding" not in videos[0]


def test_list_videos_empty_db_returns_empty_list(client, mock_db):
    resp_mock = MagicMock()
    resp_mock.data = []
    mock_db.table.return_value.select.return_value.order.return_value.execute.return_value = (
        resp_mock
    )

    response = client.get("/videos")
    assert response.status_code == 200
    assert response.json() == []


def test_list_videos_db_error_returns_502(client, mock_db):
    mock_db.table.return_value.select.return_value.order.return_value.execute.side_effect = (
        Exception("Connection refused")
    )

    response = client.get("/videos")
    assert response.status_code == 502
