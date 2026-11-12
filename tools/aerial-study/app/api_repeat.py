"""TV repeat-learning API: audio-only cards, no ASR and no text judge."""
from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from . import auth, repeat_learning
from .config import Settings
from .deps import get_settings, require_device_dep

router = APIRouter(prefix="/api/v1/repeat-learning", tags=["repeat-learning"])


class RepeatSessionRequest(BaseModel):
    deviceId: str | None = Field(default=None, max_length=128)
    ageGroupId: int | None = None
    subjectId: int | None = None


class RepeatAttemptRequest(BaseModel):
    cardId: int
    audio: str
    audioFormat: str = "audio/wav"


def _token(request: Request, body_token: str | None = None) -> str:
    return auth.provided_device_token(request) or (body_token or "").strip()


def _decode(value: str) -> bytes:
    payload = value.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise repeat_learning.RepeatLearningError("audio must be base64-encoded", status_code=400) from exc


@router.post("/sessions", status_code=201)
def create_repeat_session(
    payload: RepeatSessionRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    auth.require_device(settings, _token(request))
    return repeat_learning.start_session(
        settings,
        device_id=payload.deviceId or request.headers.get("X-Device-Id", ""),
        age_group_id=payload.ageGroupId,
        subject_id=payload.subjectId,
    )


@router.get("/sessions/{session_id}")
def get_repeat_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    _: str = Depends(require_device_dep),
) -> dict[str, Any]:
    row = repeat_learning._row(settings, session_id)
    if not row:
        raise repeat_learning.RepeatLearningError("session not found", status_code=404)
    return repeat_learning.session_view(settings, row)


@router.post("/sessions/{session_id}/attempts")
def submit_repeat_attempt(
    session_id: str,
    payload: RepeatAttemptRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    auth.require_device(settings, _token(request))
    audio = _decode(payload.audio)
    if not audio:
        raise repeat_learning.RepeatLearningError("audio is empty", status_code=422)
    if len(audio) > 1_500_000:
        raise repeat_learning.RepeatLearningError("audio is too large", status_code=413)
    return repeat_learning.submit_attempt(settings, session_id, card_id=payload.cardId, audio=audio)
