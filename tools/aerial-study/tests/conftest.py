"""Shared pytest fixtures.

The suite never touches the network or a real whisper model: AI generation is
monkeypatched and ASR is replaced with an in-memory fake.  Every test gets an
isolated temporary DATA_DIR.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

DEVICE_TOKEN = "test-device-token"
ADMIN_PASSWORD = "test-admin-password"
DEEPSEEK_TEST_KEY = "test-deepseek-key-never-returned"

# 1x1 transparent PNG (valid magic + IEND chunk).
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8B"
    "QDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def make_wav(seconds: float = 0.2, sample_rate: int = 16000) -> bytes:
    frames = b"\x00\x00" * int(sample_rate * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
    return buffer.getvalue()




@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STUDY_DEVICE_TOKEN", DEVICE_TOKEN)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", DEEPSEEK_TEST_KEY)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "")
    monkeypatch.setenv("XIAOMI_MIMO_BASE_URL", "")
    monkeypatch.setenv("XIAOMI_MIMO_MODEL", "")
    monkeypatch.setenv("GENERATION_INLINE", "1")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("QUESTIONS_PER_SESSION", "5")
    monkeypatch.setenv("SESSION_TTL_HOURS", "24")

    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def admin_client(app):
    test_client = TestClient(app)
    response = test_client.post(
        "/admin/login",
        data={"password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return test_client


@pytest.fixture
def tv_client(app):
    test_client = TestClient(app)
    test_client.headers.update({"X-Study-Token": DEVICE_TOKEN})
    return test_client


@pytest.fixture
def image_factory(admin_client):
    def create(
        filename: str = "picture.png",
        data: bytes = PNG_BYTES,
        content_type: str = "image/png",
        title: str = "picture",
    ) -> dict:
        response = admin_client.post(
            "/api/v1/admin/materials",
            files={"file": (filename, data, content_type)},
            data={"title": title},
        )
        assert response.status_code in (200, 201), response.text
        return response.json()["material"]

    return create


@pytest.fixture
def question_factory(admin_client, image_factory):
    def create(
        count: int = 5,
        *,
        status: str = "active",
        lang: str = "en",
        prefix: str = "item",
        image: dict | None = None,
    ) -> dict:
        material = image or image_factory(title=f"{prefix} image")
        created: list[dict] = []
        for index in range(count):
            prompt = f"{prefix} prompt {index}"
            answer = f"{prefix}{index}"
            response = admin_client.post(
                "/api/v1/admin/questions",
                json={
                    "prompt": prompt,
                    "answer": answer,
                    "imageId": material["sha256"],
                    "lang": lang,
                    "difficulty": (index % 5) + 1,
                    "status": status,
                },
            )
            assert response.status_code == 201, response.text
            created.append(response.json()["question"])
        return {
            "image": material,
            "questions": created,
            "ids": [question["id"] for question in created],
            "answers": {question["id"]: question["answer"] for question in created},
        }

    return create


@pytest.fixture
def seeded(question_factory):
    """Five active questions plus a small answer map."""
    return question_factory(5, prefix="seed")
