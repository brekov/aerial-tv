"""Health, root redirect and basic app wiring."""

from __future__ import annotations

from tests.conftest import ADMIN_PASSWORD, DEEPSEEK_TEST_KEY


def test_health_reports_components_without_secrets(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "aerial-study"
    assert payload["database"] == "ok"
    assert payload["auth"]["deviceTokenRequired"] is True
    assert payload["auth"]["adminConfigured"] is True
    assert "providers" in payload["ai"]
    # Secrets must never appear in a health payload.
    assert ADMIN_PASSWORD not in response.text
    assert DEEPSEEK_TEST_KEY not in response.text


def test_health_alias_and_root_redirect(client):
    assert client.get("/api/v1/health").status_code == 200
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/admin"


def test_openapi_available(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/repeat-learning/sessions" in paths
    assert "/api/v1/repeat-learning/sessions/{session_id}/attempts" in paths
    assert "/api/v1/admin/materials" in paths
    assert "/api/v1/admin/questions" in paths
