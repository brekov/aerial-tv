"""ASR engine internals with faster-whisper replaced by a fake model.

These tests cover lazy loading, the single-worker queue and the missing-dependency
path; real transcription accuracy is out of scope for the offline test suite.
"""

from __future__ import annotations

import threading
import time

import pytest

from app import asr as asr_module
from app.asr import AsrEngine, AsrUnavailable
from tests.conftest import make_wav


class _Info:
    language = "en"
    duration = 0.4


class _Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls: list[dict] = []

    def transcribe(self, path, language=None, beam_size=1, vad_filter=True):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            self.calls.append(
                {
                    "path": path,
                    "language": language,
                    "beam_size": beam_size,
                    "vad_filter": vad_filter,
                }
            )
            return iter([_Segment(" hello"), _Segment(" world ")]), _Info()
        finally:
            with self.lock:
                self.active -= 1


def _engine_with_fake(app, monkeypatch):
    engine = AsrEngine(app.state.settings)
    fake = FakeModel()

    def fake_loader():
        engine._model = fake
        return fake

    monkeypatch.setattr(asr_module, "asr_available", lambda: True)
    monkeypatch.setattr(engine, "_load_model", fake_loader)
    return engine, fake


def test_engine_lazily_loads_model_and_joins_segments(app, monkeypatch):
    engine, fake = _engine_with_fake(app, monkeypatch)
    assert engine.status()["loaded"] is False

    result = engine.transcribe_bytes(make_wav(), suffix=".wav")
    assert result["text"] == "hello world"
    assert result["language"] == "en"
    assert engine.status()["loaded"] is True
    assert fake.calls[0]["language"] is None  # ASR_LANGUAGE=auto
    assert fake.calls[0]["beam_size"] == app.state.settings.asr_beam_size
    assert fake.calls[0]["vad_filter"] is True
    assert list(app.state.settings.data_dir.glob("tmp*.wav")) == []


def test_engine_serialises_requests_through_one_worker(app, monkeypatch):
    engine, fake = _engine_with_fake(app, monkeypatch)
    results: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        value = engine.transcribe_bytes(make_wav(0.05), suffix=".wav")
        with lock:
            results.append(value["text"])

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results == ["hello world", "hello world", "hello world"]
    assert fake.max_active == 1  # concurrency is always 1
    assert len(fake.calls) == 3


def test_engine_reports_missing_faster_whisper(app, monkeypatch):
    engine = AsrEngine(app.state.settings)
    monkeypatch.setattr(asr_module, "asr_available", lambda: False)
    with pytest.raises(AsrUnavailable) as excinfo:
        engine.transcribe_bytes(make_wav(), suffix=".wav")
    assert excinfo.value.status_code == 503


def test_engine_rejects_when_queue_is_full(app, monkeypatch):
    import queue

    engine = AsrEngine(app.state.settings)
    engine._queue = queue.Queue(maxsize=1)
    engine.settings.asr_timeout_seconds = 0.05
    monkeypatch.setattr(asr_module, "asr_available", lambda: True)
    monkeypatch.setattr(engine, "_ensure_worker", lambda: None)

    with pytest.raises(asr_module.AsrTimeout):
        engine.transcribe_bytes(make_wav(), suffix=".wav")
    with pytest.raises(asr_module.AsrBusy):
        engine.transcribe_bytes(make_wav(), suffix=".wav")
