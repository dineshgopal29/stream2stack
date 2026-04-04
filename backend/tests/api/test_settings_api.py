"""
API tests for /settings endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _make_db_response(data):
    resp = MagicMock()
    resp.data = data
    return resp


SAMPLE_SETTINGS = {
    "user_id": "user-1",
    "email_frequency": "weekly",
    "topics": ["Python", "FastAPI"],
    "playlist_urls": [],
    "recipient_email": "user@example.com",
}


# ---------------------------------------------------------------------------
# GET /settings/{user_id}
# ---------------------------------------------------------------------------


def test_get_settings_returns_200(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(SAMPLE_SETTINGS)
    )

    response = client.get("/settings/user-1")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "user-1"
    assert data["email_frequency"] == "weekly"
    assert "Python" in data["topics"]


def test_get_settings_not_found_returns_404(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        _make_db_response(None)
    )

    response = client.get("/settings/unknown-user")
    assert response.status_code == 404


def test_get_settings_db_error_returns_502(client, mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = (
        Exception("DB down")
    )

    response = client.get("/settings/user-1")
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# PUT /settings/{user_id}
# ---------------------------------------------------------------------------


def test_put_settings_returns_200(client, mock_db):
    upserted = {**SAMPLE_SETTINGS, "topics": ["Go", "Kubernetes"]}
    mock_db.table.return_value.upsert.return_value.execute.return_value = (
        _make_db_response([upserted])
    )

    response = client.put(
        "/settings/user-1",
        json={
            "user_id": "user-1",
            "email_frequency": "weekly",
            "topics": ["Go", "Kubernetes"],
            "playlist_urls": [],
            "recipient_email": "user@example.com",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "user-1"
    assert "Go" in data["topics"]


def test_put_settings_mismatched_user_id_returns_422(client):
    response = client.put(
        "/settings/user-1",
        json={
            "user_id": "user-2",  # mismatch with path param
            "email_frequency": "weekly",
            "topics": [],
            "playlist_urls": [],
        },
    )
    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]


def test_put_settings_db_error_returns_502(client, mock_db):
    mock_db.table.return_value.upsert.return_value.execute.side_effect = Exception(
        "Constraint violation"
    )

    response = client.put(
        "/settings/user-1",
        json={
            "user_id": "user-1",
            "email_frequency": "daily",
            "topics": [],
            "playlist_urls": [],
        },
    )
    assert response.status_code == 502
