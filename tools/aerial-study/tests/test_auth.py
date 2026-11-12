"""Authentication: TV device token and admin password sessions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import ADMIN_PASSWORD, DEVICE_TOKEN


def test_admin_api_requires_login(client):
    response = client.get("/api/v1/admin/questions")
    assert response.status_code == 401
    redirect = client.get("/admin", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"].startswith("/admin/login")


def test_admin_login_rejects_wrong_password(client):
    response = client.post("/admin/login", data={"password": "nope"})
    assert response.status_code == 401
    assert "wrong password" in response.text


def test_admin_login_json_returns_bearer_token(app):
    client = TestClient(app)
    response = client.post(
        "/admin/login",
        json={"password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    assert token

    bearer = TestClient(app)
    bearer.headers.update({"Authorization": f"Bearer {token}"})
    assert bearer.get("/api/v1/admin/questions").status_code == 200


def test_admin_logout_invalidates_cookie(admin_client):
    assert admin_client.get("/api/v1/admin/questions").status_code == 200
    response = admin_client.post("/admin/logout", follow_redirects=False)
    assert response.status_code == 303
    assert admin_client.get("/api/v1/admin/questions").status_code == 401


def test_admin_disabled_when_password_missing(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    from app.main import create_app

    disabled_app = create_app()
    client = TestClient(disabled_app)
    assert client.get("/admin/login").status_code == 200
    assert "Admin is disabled" in client.get("/admin/login").text
    assert client.post("/admin/login", data={"password": ""}).status_code == 503
    assert client.get("/api/v1/admin/questions").status_code == 503
    # The TV API still works when the admin plane is disabled.
    assert disabled_app.state.settings.admin_configured is False


def test_device_auth_can_be_disabled(app, seeded, monkeypatch):
    monkeypatch.setenv("STUDY_DEVICE_TOKEN", "")
    from app.main import create_app

    open_app = create_app()
    client = TestClient(open_app)
    # Same temp DATA_DIR, so the seeded active questions are visible.
    assert open_app.state.settings.device_auth_enabled is False
    response = client.post("/api/v1/sessions", json={})
    assert response.status_code == 201
    assert client.get("/health").json()["auth"]["deviceTokenRequired"] is False
