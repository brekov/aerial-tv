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

from . import auth
from .config import Settings
from .db import check_db
from .deps import get_settings, require_device_dep
from .materials import MaterialError, get_image_material, material_path
from .providers import provider_status
from .questions import count_active
from .sessions import SessionError
from .taxonomy import TaxonomyError, all_taxonomy
from .upload_tokens import UploadTokenError, create_token, validate_token
from .materials import MaterialError, save_material, admin_material_dict
from .util import iso, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tv"])


class StudyUploadTokenRequest(BaseModel):
    categoryId: int | None = None
    ageGroupId: int | None = None
    subjectId: int | None = None
    maxUploads: int = 10
    minutes: int = 10


def _request_token(request: Request, body_token: str | None) -> str:
    return auth.provided_device_token(request) or (body_token or "").strip()


@router.get("/health", include_in_schema=False)
def health(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
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


@router.post("/study/upload-tokens")
def study_upload_token(
    payload: StudyUploadTokenRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    _: str = Depends(require_device_dep),
) -> dict[str, Any]:
    base = settings.public_base_url or str(request.base_url).rstrip("/")
    try:
        token = create_token(
            settings,
            category_id=payload.categoryId,
            age_group_id=payload.ageGroupId,
            subject_id=payload.subjectId,
            created_by="tv",
            base_url=base,
            max_uploads=payload.maxUploads,
            minutes=payload.minutes,
        )
    except Exception as exc:
        raise SessionError(getattr(exc, "message", str(exc)), status_code=getattr(exc, "status_code", 422)) from exc
    return {"token": token}


@router.get("/mobile/upload-tokens/{raw_token}")
def mobile_upload_token_info(raw_token: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        data = validate_token(settings, raw_token)
    except UploadTokenError as exc:
        raise SessionError(exc.message, status_code=exc.status_code) from exc
    return {
        "token": {
            "id": data["id"],
            "expiresAt": data["expires_at"],
            "maxUploads": data["max_uploads"],
            "usedCount": data["used_count"],
            "categoryId": data["category_id"],
            "ageGroupId": data["age_group_id"],
            "subjectId": data["subject_id"],
        },
        "taxonomy": all_taxonomy(settings),
    }


@router.post("/mobile/uploads", status_code=201)
def mobile_upload(
    raw_token: str = Form(...),
    file: UploadFile = File(...),
    categoryId: int | None = Form(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        data = validate_token(settings, raw_token, consume=True)
        content = file.file.read(settings.image_max_mb * 1024 * 1024 + 1)
        material, created = save_material(
            settings,
            filename=file.filename or "phone-upload",
            content_type=file.content_type or "",
            data=content,
            category_id=categoryId if categoryId is not None else data["category_id"],
            age_group_id=data["age_group_id"],
            subject_id=data["subject_id"],
            source="mobile",
        )
    except (UploadTokenError, TaxonomyError) as exc:
        raise SessionError(exc.message, status_code=exc.status_code) from exc
    except MaterialError as exc:
        raise SessionError(exc.message, status_code=exc.status_code) from exc
    return {"material": admin_material_dict(settings, material), "deduplicated": not created}


@router.get("/images/{image_id}")
def get_image(
    image_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    token = auth.provided_device_token(request)
    authorized = auth.verify_device_token(settings, token)
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
