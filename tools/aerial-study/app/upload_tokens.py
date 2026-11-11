"""Short-lived capability tokens for phone material uploads."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from .config import Settings
from .db import read_session, session
from .taxonomy import TaxonomyError, age_group_exists, parse_category, subject_exists
from .util import iso, new_id, parse_iso, utcnow


class UploadTokenError(Exception):
    def __init__(self, message: str, status_code: int = 410) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(
    settings: Settings,
    *,
    category_id: int | None,
    age_group_id: int | None,
    subject_id: int | None,
    created_by: str,
    base_url: str,
    max_uploads: int = 10,
    minutes: int = 10,
) -> dict[str, Any]:
    if not age_group_exists(settings, age_group_id):
        raise TaxonomyError("age group not found", status_code=404)
    if not subject_exists(settings, subject_id):
        raise TaxonomyError("subject not found", status_code=404)
    if category_id is not None:
        parse_category(settings, category_id)
    raw = secrets.token_urlsafe(32)
    token_id = new_id()
    expires = iso(utcnow() + timedelta(minutes=max(1, min(minutes, 60))))
    with session(settings) as conn:
        conn.execute(
            """INSERT INTO mobile_upload_tokens(
                id, token_hash, expires_at, max_uploads, used_count,
                category_id, age_group_id, subject_id, created_at, created_by)
               VALUES(?,?,?,?,0,?,?,?,?,?)""",
            (token_id, _hash(raw), expires, max(1, min(max_uploads, 50)),
             category_id, age_group_id, subject_id, iso(utcnow()), created_by),
        )
    root = base_url.rstrip("/")
    return {
        "id": token_id,
        "token": raw,
        "url": f"{root}/m/upload/{raw}",
        "expiresAt": expires,
        "maxUploads": max_uploads,
        "usedCount": 0,
        "categoryId": category_id,
        "ageGroupId": age_group_id,
        "subjectId": subject_id,
    }


def validate_token(settings: Settings, raw: str, *, consume: bool = False) -> dict[str, Any]:
    token_hash = _hash(raw)
    with session(settings) if consume else read_session(settings) as conn:
        row = conn.execute(
            "SELECT * FROM mobile_upload_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if not row:
            raise UploadTokenError("upload link is invalid", status_code=404)
        data = dict(row)
        if parse_iso(data["expires_at"]) <= utcnow():
            raise UploadTokenError("upload link expired", status_code=410)
        if int(data["used_count"]) >= int(data["max_uploads"]):
            raise UploadTokenError("upload link limit reached", status_code=429)
        if consume:
            conn.execute(
                "UPDATE mobile_upload_tokens SET used_count = used_count + 1 WHERE id = ?",
                (data["id"],),
            )
            data["used_count"] = int(data["used_count"]) + 1
    return data
