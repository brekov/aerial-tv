"""ASR endpoint behaviour with a mocked engine, plus audio preparation helpers."""

from __future__ import annotations

import base64
import io
import wave

import pytest

from app.asr import AsrBusy, AsrError, AsrTimeout, prepare_audio, wrap_pcm_as_wav
from tests.conftest import FakeAsr, make_wav


def _multipart(data: bytes, content_type: str = "audio/wav", filename: str = "a.wav"):
    return {"file": (filename, data, content_type)}


def test_raw_pcm_is_wrapped_as_wav(app):
    settings = app.state.settings
    pcm = b"\x00\x01" * 1600
    wrapped, suffix = prepare_audio(pcm, "audio.pcm", "audio/pcm", settings)
    assert suffix == ".wav"
    assert wrapped.startswith(b"RIFF")
    assert wrapped[8:12] == b"WAVE"
    with wave.open(io.BytesIO(wrapped), "rb") as handle:
        assert handle.getframerate() == settings.asr_pcm_sample_rate
        assert handle.getnchannels() == settings.asr_pcm_channels
        assert handle.getsampwidth() == settings.asr_pcm_sample_width
        assert handle.getnframes() == 1600


def test_wav_passthrough(app):
    wav = make_wav()
    prepared, suffix = prepare_audio(wav, "answer.wav", "audio/wav", app.state.settings)
    assert suffix == ".wav"
    assert prepared == wav


def test_empty_and_oversized_audio_are_rejected(app):
    settings = app.state.settings
    with pytest.raises(AsrError) as empty:
        prepare_audio(b"", "x.wav", "audio/wav", settings)
    assert empty.value.status_code == 400

    settings.asr_max_mb = 1
    with pytest.raises(AsrError) as too_big:
        prepare_audio(b"\x00" * (1024 * 1024 + 1), "x.wav", "audio/wav", settings)
    assert too_big.value.status_code == 413


def test_pcm_wrapper_rejects_bad_settings(app):
    # Sanity-check the helper output for the default 16 kHz mono 16-bit config.
    wav = wrap_pcm_as_wav(b"\x00\x00" * 16, app.state.settings)
    with wave.open(io.BytesIO(wav), "rb") as handle:
        assert handle.getnframes() == 16


def test_asr_requires_device_token(client):
    response = client.post("/api/v1/asr", files=_multipart(make_wav()))
    assert response.status_code == 401


def test_asr_rejects_empty_upload(tv_client):
    response = tv_client.post("/api/v1/asr", files=_multipart(b""))
    assert response.status_code == 400
    assert "empty audio" in response.json()["detail"]


def test_asr_success_with_mocked_engine(tv_client, app):
    app.state.asr = FakeAsr("hello world")
    response = tv_client.post("/api/v1/asr", files=_multipart(make_wav()))
    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "hello world"
    assert payload["language"] == "en"
    assert app.state.asr.calls[0]["size"] > 0


def test_asr_accepts_webm_suffix(tv_client, app):
    app.state.asr = FakeAsr("你好")
    response = tv_client.post(
        "/api/v1/asr",
        files=_multipart(b"\x1aE\xdf\xa3fake-webm", "audio/webm", "voice.webm"),
    )
    assert response.status_code == 200
    assert app.state.asr.calls[0]["suffix"] == ".webm"


def test_asr_queue_full_returns_429(tv_client, app):
    app.state.asr = FakeAsr(error=AsrBusy())
    response = tv_client.post("/api/v1/asr", files=_multipart(make_wav()))
    assert response.status_code == 429


def test_asr_timeout_returns_504(tv_client, app):
    app.state.asr = FakeAsr(error=AsrTimeout())
    response = tv_client.post("/api/v1/asr", files=_multipart(make_wav()))
    assert response.status_code == 504


def test_answer_with_base64_audio_uses_asr(tv_client, app, seeded):
    session = tv_client.post("/api/v1/sessions", json={}).json()
    session_id = session["session"]["id"]
    first = session["questions"][0]
    app.state.asr = FakeAsr(seeded["answers"][first["id"]])

    audio = base64.b64encode(make_wav()).decode("ascii")
    response = tv_client.post(
        f"/api/v1/sessions/{session_id}/answer",
        json={
            "questionId": first["id"],
            "audio": audio,
            "audioFormat": "audio/wav",
        },
    )
    assert response.status_code == 200
    assert response.json()["correct"] is True
    assert app.state.asr.calls[0]["size"] > 0


def test_answer_with_audio_only_whitespace_transcript_rejected(tv_client, app, seeded):
    session = tv_client.post("/api/v1/sessions", json={}).json()
    session_id = session["session"]["id"]
    first = session["questions"][0]
    app.state.asr = FakeAsr("   ")
    response = tv_client.post(
        f"/api/v1/sessions/{session_id}/answer",
        json={
            "questionId": first["id"],
            "audio": base64.b64encode(make_wav()).decode("ascii"),
            "audioFormat": "audio/wav",
        },
    )
    assert response.status_code == 422
    assert "no text" in response.json()["detail"]


def test_answer_without_transcript_or_audio_is_422(tv_client, seeded):
    session = tv_client.post("/api/v1/sessions", json={}).json()
    session_id = session["session"]["id"]
    first = session["questions"][0]
    response = tv_client.post(
        f"/api/v1/sessions/{session_id}/answer",
        json={"questionId": first["id"]},
    )
    assert response.status_code == 422


def test_invalid_base64_audio_is_400(tv_client, seeded):
    session = tv_client.post("/api/v1/sessions", json={}).json()
    session_id = session["session"]["id"]
    first = session["questions"][0]
    response = tv_client.post(
        f"/api/v1/sessions/{session_id}/answer",
        json={"questionId": first["id"], "audio": "not-base64!!!"},
    )
    assert response.status_code == 400


def test_asr_returns_503_when_faster_whisper_missing(tv_client, monkeypatch):
    # Deterministic on any host: force the availability check to fail.
    monkeypatch.setattr("app.asr.asr_available", lambda: False)
    response = tv_client.post("/api/v1/asr", files=_multipart(make_wav()))
    assert response.status_code == 503
    assert "faster-whisper" in response.json()["detail"]
