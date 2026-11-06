"""CPU-only speech-to-text with faster-whisper.

* The model is loaded lazily on the first request, inside the single worker
  thread, so startup stays fast and idle containers use little RAM.
* All transcription requests pass through a bounded FIFO queue processed by
  exactly one worker: concurrency is always 1, which keeps CPU latency
  predictable on a NAS.
* faster-whisper is an optional runtime dependency for tests/development; if it
  is not installed the endpoint returns a clear 503 instead of crashing.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import queue
import tempfile
import threading
import time
import wave
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)

_SUFFIX_BY_CONTENT_TYPE = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
}


class AsrError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AsrBusy(AsrError):
    def __init__(self) -> None:
        super().__init__("ASR queue is full, retry shortly", status_code=429)


class AsrTimeout(AsrError):
    def __init__(self) -> None:
        super().__init__("ASR request timed out", status_code=504)


class AsrUnavailable(AsrError):
    def __init__(self, message: str = "ASR is not available") -> None:
        super().__init__(message, status_code=503)


def asr_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def wrap_pcm_as_wav(data: bytes, settings: Settings) -> bytes:
    """Wrap headerless 16-bit PCM in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(settings.asr_pcm_channels)
        output.setsampwidth(settings.asr_pcm_sample_width)
        output.setframerate(settings.asr_pcm_sample_rate)
        output.writeframes(data)
    return buffer.getvalue()


def prepare_audio(
    data: bytes, filename: str, content_type: str, settings: Settings
) -> tuple[bytes, str]:
    """Return ``(audio_bytes, suffix)`` suitable for faster-whisper.

    Raw PCM is wrapped into WAV; WAV/webm/ogg/mp3/m4a are passed through
    (faster-whisper decodes containers with PyAV, and the Docker image also
    installs ffmpeg for webm/opus).
    """
    if not data:
        raise AsrError("empty audio upload", status_code=400)
    if len(data) > settings.asr_max_mb * 1024 * 1024:
        raise AsrError(f"audio too large (max {settings.asr_max_mb} MB)", status_code=413)
    content_type = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename or "").suffix.lower()
    is_wav = data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    is_raw_pcm = (
        content_type in {"audio/pcm", "audio/l16", "application/octet-stream"}
        and suffix in {"", ".pcm", ".raw"}
    ) or suffix in {".pcm", ".raw"}
    if is_raw_pcm and not is_wav:
        return wrap_pcm_as_wav(data, settings), ".wav"
    if is_wav:
        return data, ".wav"
    if suffix:
        return data, suffix
    return data, _SUFFIX_BY_CONTENT_TYPE.get(content_type, ".bin")


class AsrEngine:
    """Serialised, lazy-loading faster-whisper worker."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._queue: queue.Queue[tuple[bytes, str, str | None, Future]] = queue.Queue(
            maxsize=settings.asr_queue_size
        )
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._model: Any | None = None
        self._model_error: str | None = None
        self._model_lock = threading.Lock()
        self._busy = threading.Event()

    # -- public API --------------------------------------------------------

    def transcribe_bytes(
        self, data: bytes, *, suffix: str = ".wav", language: str | None = None
    ) -> dict[str, Any]:
        if not asr_available():
            raise AsrUnavailable("faster-whisper is not installed in this environment")
        future: Future = Future()
        try:
            self._queue.put_nowait((data, suffix, language, future))
        except queue.Full as exc:
            raise AsrBusy() from exc
        self._ensure_worker()
        try:
            return future.result(timeout=self.settings.asr_timeout_seconds)
        except FutureTimeout as exc:
            raise AsrTimeout() from exc

    def status(self) -> dict[str, Any]:
        return {
            "available": asr_available(),
            "model": self.settings.asr_model,
            "device": self.settings.asr_device,
            "computeType": self.settings.asr_compute_type,
            "language": self.settings.asr_language,
            "loaded": self._model is not None,
            "queued": self._queue.qsize(),
            "busy": self._busy.is_set(),
            "queueCapacity": self._queue.maxsize,
            "loadError": self._model_error,
        }

    def preload(self) -> None:
        """Warm the model in the worker thread (used only by tests/dev)."""
        self._ensure_worker()
        self._queue.put((b"", ".synthetic", None, Future()))

    # -- worker ------------------------------------------------------------

    def _ensure_worker(self) -> None:
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._worker_loop,
                    name="asr-worker",
                    daemon=True,
                )
                self._thread.start()

    def _worker_loop(self) -> None:
        while True:
            data, suffix, language, future = self._queue.get()
            if suffix == ".synthetic":  # warm-up marker
                try:
                    self._load_model()
                    future.set_result({"text": "", "warmup": True})
                except AsrError as exc:
                    future.set_exception(exc)
                finally:
                    self._queue.task_done()
                continue
            self._busy.set()
            try:
                result = self._transcribe(data, suffix, language)
                future.set_result(result)
            except AsrError as exc:
                if not future.cancelled():
                    future.set_exception(exc)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("ASR worker crashed")
                if not future.cancelled():
                    future.set_exception(
                        AsrError(f"ASR failed: {type(exc).__name__}", status_code=500)
                    )
            finally:
                self._busy.clear()
                self._queue.task_done()

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel  # type: ignore
            except Exception as exc:  # pragma: no cover - import environment
                self._model_error = "faster-whisper is not installed"
                raise AsrUnavailable(self._model_error) from exc
            download_root = str(self.settings.data_dir / "models")
            started = time.monotonic()
            try:
                model = WhisperModel(
                    self.settings.asr_model,
                    device=self.settings.asr_device,
                    compute_type=self.settings.asr_compute_type,
                    download_root=download_root,
                )
            except Exception as exc:
                self._model_error = f"model load failed: {type(exc).__name__}"
                logger.error("faster-whisper model load failed: %s", type(exc).__name__)
                raise AsrUnavailable(
                    "ASR model failed to load; check ASR_MODEL and the container logs"
                ) from exc
            self._model = model
            self._model_error = None
            logger.info(
                "faster-whisper model '%s' loaded on %s/%s in %.1fs",
                self.settings.asr_model,
                self.settings.asr_device,
                self.settings.asr_compute_type,
                time.monotonic() - started,
            )
            return model

    def _transcribe(self, data: bytes, suffix: str, language: str | None) -> dict[str, Any]:
        model = self._load_model()
        selected_language = language or self.settings.asr_language
        if selected_language in {"", "auto"}:
            selected_language = None
        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        path = ""
        started = time.monotonic()
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix, dir=str(self.settings.data_dir), delete=False
            ) as handle:
                handle.write(data)
                path = handle.name
            segments, info = model.transcribe(
                path,
                language=selected_language,
                beam_size=self.settings.asr_beam_size,
                vad_filter=True,
            )
            text = "".join(segment.text for segment in segments).strip()
        finally:
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
        duration = round(time.monotonic() - started, 2)
        logger.info(
            "ASR finished in %.2fs (audio %.1fs, lang %s)",
            duration,
            getattr(info, "duration", 0.0) or 0.0,
            getattr(info, "language", "auto") if "info" in locals() else "auto",
        )
        detected = getattr(info, "language", None) if "info" in locals() else None
        return {
            "text": text,
            "language": detected or selected_language or "auto",
            "audioSeconds": round(float(getattr(info, "duration", 0.0) or 0.0), 2),
            "processingSeconds": duration,
        }
