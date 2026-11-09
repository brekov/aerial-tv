"""AI generation with a mocked provider: drafts only, failure handling, config."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.providers import ProviderError
from tests.conftest import DEEPSEEK_TEST_KEY


def _fake_generator(settings, *, provider_name, image_bytes, mime_type, lang, count):
    assert image_bytes.startswith(b"\x89PNG")
    assert mime_type == "image/png"
    config = SimpleNamespace(name=provider_name or "deepseek", model="fake-vl")
    items = [
        {
            "prompt": f"AI prompt {index}",
            "answer": f"ai-answer-{index}",
            "explanation": "generated",
            "difficulty": 2,
        }
        for index in range(count)
    ]
    return items, config


def _trigger(admin_client, image, **overrides):
    payload = {
        "materialId": image["sha256"],
        "provider": "deepseek",
        "lang": "en",
        "count": 3,
    }
    payload.update(overrides)
    return admin_client.post("/api/v1/admin/generate", json=payload)


def test_generation_creates_draft_questions_only(admin_client, image_factory, monkeypatch):
    monkeypatch.setattr("app.generation.generate_word_image_questions", _fake_generator)
    image = image_factory()

    response = _trigger(admin_client, image)
    assert response.status_code == 202
    job = response.json()["job"]
    assert job["status"] == "succeeded", job
    # A word-image card has exactly one target word; the API ignores count for this type.
    assert len(job["questionIds"]) == 1
    assert job["provider"] == "deepseek"

    drafts = admin_client.get("/api/v1/admin/questions?status=draft").json()["items"]
    assert len(drafts) == 1
    assert all(item["source"] == "ai" for item in drafts)
    assert all(item["status"] == "draft" for item in drafts)
    assert all(item["imageId"] == image["sha256"] for item in drafts)
    assert all(item["meta"]["generationJobId"] == job["id"] for item in drafts)

    active = admin_client.get("/api/v1/admin/questions?status=active").json()
    assert active["total"] == 0
    assert active["items"] == []

    fetched = admin_client.get(f"/api/v1/admin/jobs/{job['id']}").json()["job"]
    assert fetched["status"] == "succeeded"
    assert fetched["result"]["model"] == "fake-vl"
    listed = admin_client.get("/api/v1/admin/jobs").json()["items"]
    assert any(item["id"] == job["id"] for item in listed)


def test_generation_failure_is_recorded(admin_client, image_factory, monkeypatch, caplog):
    def failing(*args, **kwargs):
        raise ProviderError("provider returned HTTP 500: upstream unavailable")

    monkeypatch.setattr("app.generation.generate_word_image_questions", failing)
    caplog.set_level(logging.DEBUG)
    image = image_factory()

    response = _trigger(admin_client, image)
    assert response.status_code == 202
    job = response.json()["job"]
    assert job["status"] == "failed"
    assert "upstream unavailable" in job["error"]
    assert admin_client.get("/api/v1/admin/questions?status=draft").json()["total"] == 0
    assert DEEPSEEK_TEST_KEY not in caplog.text


def test_generation_fails_clearly_without_api_key(admin_client, image_factory, app):
    image = image_factory()
    app.state.settings.deepseek_api_key = ""
    response = _trigger(admin_client, image)
    assert response.status_code == 202
    job = response.json()["job"]
    assert job["status"] == "failed"
    assert "not configured" in job["error"]

    # Manual draft creation must keep working without any AI key.
    manual = admin_client.post(
        "/api/v1/admin/questions",
        json={
            "prompt": "Manual prompt",
            "answer": "manual",
            "imageId": image["sha256"],
            "lang": "en",
        },
    )
    assert manual.status_code == 201
    assert manual.json()["question"]["source"] == "manual"


def test_unconfigured_second_provider_reports_error(admin_client, image_factory):
    image = image_factory()
    response = _trigger(admin_client, image, provider="xiaomi_mimo")
    assert response.status_code == 202
    job = response.json()["job"]
    assert job["status"] == "failed"
    assert "xiaomi_mimo" in job["error"]


def test_provider_api_never_returns_keys(admin_client):
    response = admin_client.get("/api/v1/admin/providers")
    assert response.status_code == 200
    assert DEEPSEEK_TEST_KEY not in response.text
    payload = response.json()
    assert payload["providers"]["deepseek"]["hasApiKey"] is True
    assert payload["providers"]["deepseek"]["keySource"] == "env"
    assert payload["providers"]["xiaomi_mimo"]["hasApiKey"] is False
    assert payload["providers"]["deepseek"]["configured"] is True


def test_provider_routing_can_be_updated(admin_client):
    response = admin_client.put(
        "/api/v1/admin/providers/deepseek",
        json={
            "baseUrl": "https://gateway.example.com/v1",
            "model": "custom-vision-model",
            "authHeader": "X-API-Key",
        },
    )
    assert response.status_code == 200
    info = response.json()["providers"]["deepseek"]
    assert info["baseUrl"] == "https://gateway.example.com/v1"
    assert info["model"] == "custom-vision-model"
    assert info["authHeader"] == "X-API-Key"

    invalid = admin_client.put("/api/v1/admin/providers/deepseek", json={"baseUrl": "ftp://nope"})
    assert invalid.status_code == 400

    unknown = admin_client.put("/api/v1/admin/providers/openai", json={"model": "x"})
    assert unknown.status_code == 404


def test_provider_settings_update(admin_client):
    response = admin_client.put(
        "/api/v1/admin/settings",
        json={"defaultProvider": "xiaomi_mimo", "aiJudgeEnabled": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["defaultProvider"] == "xiaomi_mimo"
    assert payload["aiJudgeEnabled"] is True
    assert admin_client.get("/api/v1/admin/providers").json()["aiJudgeEnabled"] is True


def test_optional_ai_text_judge(admin_client, image_factory, app, monkeypatch):
    from app.providers import judge_answer_ai
    from app.questions import judge_transcript

    settings = app.state.settings
    # Disabled by default: no AI call, no fallback.
    assert (
        judge_answer_ai(
            settings, question_prompt="What?", reference_answer="apple", transcript="aple"
        )
        is None
    )

    admin_client.put("/api/v1/admin/settings", json={"aiJudgeEnabled": True})
    monkeypatch.setattr("app.providers._chat", lambda *args, **kwargs: "YES")
    correct, method, detail = judge_transcript(
        settings, {"prompt": "What is this?", "answer": "apple"}, "aple"
    )
    assert correct is True
    assert method == "ai"
    assert detail["aiJudge"] is True


def test_generation_async_worker_path(app, admin_client, image_factory, monkeypatch):
    import time

    monkeypatch.setattr("app.generation.generate_word_image_questions", _fake_generator)
    app.state.settings.generation_inline = False
    image = image_factory()
    job = app.state.generation.create_job(material_id=image["sha256"], count=2, lang="zh")
    deadline = time.time() + 10
    latest = job
    while time.time() < deadline:
        latest = app.state.generation.get_job(job["id"])
        if latest["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert latest["status"] == "succeeded", latest
    assert len(latest["questionIds"]) == 2


def test_word_image_parser_one_object_and_aliases(monkeypatch):
    from types import SimpleNamespace
    from app import providers

    class Config:
        name = "deepseek"
        model = "vision"
        configured = True

    monkeypatch.setattr(providers, "get_provider_config", lambda settings, name=None: Config())
    monkeypatch.setattr(providers, "_chat", lambda *args, **kwargs: '{"prompt":"请读出图中醒目的词语。","answer":"bear","aliases":["bear","bears"]}')
    questions, config = providers.generate_word_image_questions(
        SimpleNamespace(), provider_name="deepseek", image_bytes=b"png",
        mime_type="image/png", lang="en", count=5,
    )
    assert config.name == "deepseek"
    assert len(questions) == 1
    assert questions[0]["answer"] == "bear|bears"
    assert questions[0]["prompt"] == "请读出图中醒目的词语。"
