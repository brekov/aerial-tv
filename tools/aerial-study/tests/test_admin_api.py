"""Admin JSON API: uploads, question lifecycle, filters, images and stats."""

from __future__ import annotations

from tests.conftest import PNG_BYTES


def test_image_upload_is_deduplicated_and_content_addressed(admin_client, app, image_factory):
    image = image_factory(title="apple")
    sha = image["sha256"]
    stored = app.state.settings.images_dir / f"{sha}.png"
    assert stored.is_file()
    assert stored.read_bytes() == PNG_BYTES

    again = admin_client.post(
        "/api/v1/admin/materials",
        files={"file": ("another.png", PNG_BYTES, "image/png")},
        data={"title": "duplicate"},
    )
    assert again.status_code == 200
    assert again.json()["deduplicated"] is True
    assert again.json()["material"]["sha256"] == sha


def test_upload_rejects_unsupported_and_fake_images(admin_client):
    unsupported = admin_client.post(
        "/api/v1/admin/materials",
        files={"file": ("archive.zip", b"PK\x03\x04", "application/zip")},
    )
    assert unsupported.status_code == 415

    fake_image = admin_client.post(
        "/api/v1/admin/materials",
        files={"file": ("fake.png", b"not-a-png", "image/png")},
    )
    assert fake_image.status_code == 415


def test_manual_question_lifecycle(admin_client, image_factory):
    image = image_factory()
    created = admin_client.post(
        "/api/v1/admin/questions",
        json={
            "prompt": "What is this?",
            "answer": "apple|apples",
            "imageId": image["sha256"],
            "lang": "en",
            "difficulty": 2,
            "status": "draft",
        },
    )
    assert created.status_code == 201
    question = created.json()["question"]
    assert question["status"] == "draft"
    assert question["source"] == "manual"
    assert question["image"]["sha256"] == image["sha256"]

    question_id = question["id"]
    listed = admin_client.get("/api/v1/admin/questions?status=draft&search=apple").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == question_id

    activated = admin_client.post(
        f"/api/v1/admin/questions/{question_id}/status",
        json={"status": "active", "note": "checked"},
    )
    assert activated.status_code == 200
    assert activated.json()["question"]["status"] == "active"

    updated = admin_client.patch(
        f"/api/v1/admin/questions/{question_id}",
        json={"prompt": "What fruit is this?", "difficulty": 3},
    )
    assert updated.status_code == 200
    assert updated.json()["question"]["revision"] == 3
    assert updated.json()["question"]["prompt"] == "What fruit is this?"

    disabled = admin_client.post(
        f"/api/v1/admin/questions/{question_id}/status",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["question"]["status"] == "disabled"

    bad = admin_client.post(
        f"/api/v1/admin/questions/{question_id}/status", json={"status": "bogus"}
    )
    assert bad.status_code == 422

    missing = admin_client.post("/api/v1/admin/questions/999999/status", json={"status": "active"})
    assert missing.status_code == 404


def test_question_create_validation(admin_client):
    response = admin_client.post("/api/v1/admin/questions", json={"prompt": "  ", "answer": "x"})
    assert response.status_code == 422

    response = admin_client.post(
        "/api/v1/admin/questions", json={"prompt": "x", "answer": "y", "difficulty": 9}
    )
    assert response.status_code == 422


def test_image_endpoint_cache_headers(admin_client, image_factory):
    image = image_factory()
    response = admin_client.get(image["url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"].startswith("private")
    assert response.headers["etag"] == f'"{image["sha256"]}"'


def test_stats(admin_client, image_factory):
    image = image_factory()
    admin_client.post(
        "/api/v1/admin/questions",
        json={
            "prompt": "Stats draft",
            "answer": "1",
            "imageId": image["sha256"],
        },
    )
    admin_client.post(
        "/api/v1/admin/questions",
        json={
            "prompt": "Stats active",
            "answer": "2",
            "imageId": image["sha256"],
            "status": "active",
        },
    )
    stats = admin_client.get("/api/v1/admin/stats").json()
    assert stats["questions"]["draft"] == 1
    assert stats["questions"]["active"] == 1
    assert stats["materials"] == 1
    assert stats["sessions"] == 0


def test_admin_pages_render(admin_client, client):
    login_page = client.get("/admin/login")
    assert login_page.status_code == 200
    assert "Aerial Study Guard" in login_page.text
    assert "password" in login_page.text.lower()

    admin_page = admin_client.get("/admin")
    assert admin_page.status_code == 200
    for marker in ("Materials", "Manual draft", "AI generation", "Questions", "Quiz sessions"):
        assert marker in admin_page.text
    assert "admin.js" in admin_page.text


def test_admin_session_history(admin_client, tv_client, seeded):
    session = tv_client.post("/api/v1/sessions", json={}).json()
    session_id = session["session"]["id"]

    listed = admin_client.get("/api/v1/admin/sessions").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == session_id
    assert listed["items"][0]["attemptCount"] == 0

    detail = admin_client.get(f"/api/v1/admin/sessions/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["attempts"] == []
    assert admin_client.get("/api/v1/admin/sessions/unknown").status_code == 404


def test_list_filters_and_pagination(admin_client, image_factory):
    image = image_factory()
    for index in range(3):
        admin_client.post(
            "/api/v1/admin/questions",
            json={
                "prompt": f"filter me {index}",
                "answer": str(index),
                "imageId": image["sha256"],
                "lang": "zh" if index % 2 else "en",
            },
        )
    page = admin_client.get("/api/v1/admin/questions?limit=2&offset=0").json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    page2 = admin_client.get("/api/v1/admin/questions?limit=2&offset=2").json()
    assert len(page2["items"]) == 1
    english = admin_client.get("/api/v1/admin/questions?lang=en").json()
    assert english["total"] == 2


def test_material_listing(admin_client, image_factory):
    image_factory(title="one")
    response = admin_client.get("/api/v1/admin/materials?kind=image")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "image"
    assert "createdAt" in items[0]


def test_admin_page_renders_materials_and_questions(admin_client, image_factory):
    image = image_factory(title="thumbnail-material")
    question = admin_client.post(
        "/api/v1/admin/questions",
        json={
            "prompt": "Rendered prompt",
            "answer": "rendered",
            "imageId": image["sha256"],
            "lang": "en",
        },
    )
    assert question.status_code == 201
    page = admin_client.get("/admin").text
    assert "thumbnail-material" in page
    assert f"/api/v1/images/{image['sha256']}" in page
    assert "Rendered prompt" in page
    assert "rendered" in page
    assert 'data-action="edit"' in page
