"""Public / TV-facing API: health, sessions, answers, ASR and images."""

from __future__ import annotations

import base64
import binascii
import logging
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import auth, sessions
from .asr import AsrEngine, prepare_audio
from .config import Settings
from .db import check_db
from .deps import get_settings, require_device_dep
from .materials import MaterialError, get_image_material, material_path
from .providers import provider_status
from .questions import count_active
from .sessions import SessionError
from .util import iso, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tv"])

MAX_TRANSCRIPT = 2000


class SessionCreateRequest(BaseModel):
    token: str | None = None
    deviceId: str | None = Field(default=None, max_length=128)


class AnswerRequest(BaseModel):
    questionId: int
    token: str | None = None
    transcript: str | None = Field(default=None, max_length=MAX_TRANSCRIPT)
    # Base64 WAV/PCM (optionally a data: URL). Transcript wins when both are sent.
    audio: str | None = None
    audioFormat: str | None = None


def _request_token(request: Request, body_token: str | None) -> str:
    return auth.provided_device_token(request) or (body_token or "").strip()


def _decode_audio_field(value: str) -> bytes:
    payload = value.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SessionError("audio must be base64-encoded", status_code=400) from exc


_AUDIO_SUFFIX = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/pcm": ".pcm",
    "audio/l16": ".pcm",
}


def _audio_filename(audio_format: str | None) -> str:
    content_type = (audio_format or "audio/wav").split(";")[0].strip().lower()
    return f"answer{_AUDIO_SUFFIX.get(content_type, '.wav')}"


@router.get("/health", include_in_schema=False)
def health(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    asr: AsrEngine = request.app.state.asr
    started_at = getattr(request.app.state, "started_at", None)
    active = 0
    db_ok = check_db(settings)
    if db_ok:
        try:
            active = count_active(settings)
        except sqlite3.Error:  # pragma: no cover - defensive, db_ok already checked
            active = 0

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "aerial-study",
        "version": settings.version,
        "time": iso(utcnow()),
        "uptimeSeconds": round(time.monotonic() - started_at, 1) if started_at else 0,
        "database": "ok" if db_ok else "error",
        "activeQuestions": active,
        "asr": asr.status(),
        "ai": {
            "providers": {
                name: {
                    "configured": info["configured"],
                    "model": info["model"],
                }
                for name, info in provider_status(settings)["providers"].items()
            },
            "defaultProvider": provider_status(settings)["defaultProvider"],
        },
        "auth": auth.public_auth_info(settings),
    }


@router.post("/sessions", status_code=201)
def create_session(
    request: Request,
    payload: SessionCreateRequest | None = None,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    body = payload or SessionCreateRequest()
    auth.require_device(settings, _request_token(request, body.token))
    device_id = body.deviceId or request.headers.get("X-Device-Id", "")
    return sessions.create_session(settings, device_id=device_id or "")


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    _: str = Depends(require_device_dep),
) -> dict[str, Any]:
    row = sessions.load_session(settings, session_id)
    return sessions.session_view(settings, row)


@router.post("/sessions/{session_id}/answer")
def answer(
    session_id: str,
    payload: AnswerRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    auth.require_device(settings, _request_token(request, payload.token))
    transcript = (payload.transcript or "").strip()
    if not transcript:
        if not payload.audio:
            raise SessionError("transcript or audio is required", status_code=422)
        audio_bytes = _decode_audio_field(payload.audio)
        prepared, suffix = prepare_audio(
            audio_bytes,
            filename=_audio_filename(payload.audioFormat),
            content_type=payload.audioFormat or "audio/wav",
            settings=settings,
        )
        asr: AsrEngine = request.app.state.asr
        result = asr.transcribe_bytes(prepared, suffix=suffix)
        transcript = (result.get("text") or "").strip()
        if not transcript:
            raise SessionError(
                "speech recognition returned no text; send a transcript instead",
                status_code=422,
            )
    return sessions.submit_answer(
        settings,
        session_id,
        question_id=payload.questionId,
        transcript=transcript[:MAX_TRANSCRIPT],
    )


@router.post("/asr")
def transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    token: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    auth.require_device(settings, _request_token(request, token))
    data = file.file.read(settings.asr_max_mb * 1024 * 1024 + 1)
    prepared, suffix = prepare_audio(
        data,
        filename=file.filename or "audio.wav",
        content_type=file.content_type or "",
        settings=settings,
    )
    asr: AsrEngine = request.app.state.asr
    result = asr.transcribe_bytes(
        prepared,
        suffix=suffix,
        language=(language or "").strip() or None,
    )
    return {
        "text": result.get("text", ""),
        "language": result.get("language"),
        "audioSeconds": result.get("audioSeconds"),
    }


@router.get("/images/{image_id}")
def get_image(
    image_id: str,
    request: Request,
    s: str | None = None,
    settings: Settings = Depends(get_settings),
):
    token = auth.provided_device_token(request)
    authorized = auth.verify_device_token(settings, token)
    if not authorized and s:
        # The unguessable session id acts as a capability URL for TV <img> tags.
        row = sessions.get_session_row(settings, s)
        if row is not None and not sessions.is_expired(row):
            authorized = True
    if not authorized:
        # Admin cookie/bearer can preview images in the admin page.
        admin_token = auth.admin_token_from_request(request, settings)
        if auth.verify_admin_token(settings, admin_token):
            authorized = True
    if not authorized:
        return JSONResponse(status_code=401, content={"detail": "invalid session or device token"})
    material = get_image_material(settings, image_id)
    if not material or material["kind"] != "image":
        return JSONResponse(status_code=404, content={"detail": "image not found"})
    try:
        path = material_path(settings, material)
    except MaterialError:
        return JSONResponse(status_code=500, content={"detail": "invalid image path"})
    if not path.is_file():
        return JSONResponse(status_code=410, content={"detail": "image file missing"})
    return FileResponse(
        path,
        media_type=material["content_type"],
        headers={
            "Cache-Control": "private, max-age=86400",
            "ETag": f'"{material["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
