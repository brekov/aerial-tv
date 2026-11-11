"""Content-addressed material storage (images today, PDF/text for future types)."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from .config import Settings
from .db import read_session, session
from .util import iso, json_dumps, sha256_bytes, utcnow

IMAGE_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),  # additional WEBP check below
}


class MaterialError(Exception):
    """User-facing material validation error."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _detect_kind(filename: str, content_type: str, data: bytes) -> tuple[str, str]:
    """Return ``(kind, normalised_content_type)`` or raise MaterialError."""
    content_type = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename or "").suffix.lower()
    guessed, _ = mimetypes.guess_type(filename or "")

    if content_type.startswith("image/") or suffix in IMAGE_EXTENSIONS:
        detected = _detect_image_type(data)
        if not detected:
            raise MaterialError("unsupported image: expected PNG, JPEG or WebP", status_code=415)
        return "image", detected
    if content_type == "application/pdf" or suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise MaterialError("invalid PDF file", status_code=415)
        return "pdf", "application/pdf"
    if content_type.startswith("text/") or suffix in {".txt", ".md"}:
        return "text", content_type or guessed or "text/plain"
    raise MaterialError(
        "unsupported material type: upload PNG/JPEG/WebP (PDF/text are reserved "
        "for future question types)",
        status_code=415,
    )


def _extension_for(content_type: str, filename: str) -> str:
    if content_type in IMAGE_CONTENT_TYPES:
        return IMAGE_CONTENT_TYPES[content_type]
    suffix = Path(filename or "").suffix.lower()
    if suffix:
        return suffix
    return mimetypes.guess_extension(content_type) or ".bin"


def _root_for(settings: Settings, kind: str) -> Path:
    return settings.images_dir if kind == "image" else settings.materials_dir


def get_material(settings: Settings, sha256: str) -> dict[str, Any] | None:
    with read_session(settings) as conn:
        row = conn.execute("SELECT * FROM materials WHERE sha256 = ?", (sha256,)).fetchone()
        return dict(row) if row else None


def get_material_by_id(settings: Settings, material_id: int) -> dict[str, Any] | None:
    with read_session(settings) as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        return dict(row) if row else None


def list_materials(
    settings: Settings,
    kind: str | None = None,
    limit: int = 100,
    category_id: int | None = None,
    age_group_id: int | None = None,
    subject_id: int | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    where: list[str] = []
    args: list[Any] = []
    for column, value in (("kind", kind), ("category_id", category_id), ("age_group_id", age_group_id), ("subject_id", subject_id), ("source", source)):
        if value is not None:
            where.append(f"{column} = ?")
            args.append(value)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with read_session(settings) as conn:
        rows = conn.execute(f"SELECT * FROM materials {clause} ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
        return [dict(row) for row in rows]


def material_path(settings: Settings, material: dict[str, Any]) -> Path:
    root = _root_for(settings, material.get("kind", "image"))
    rel = material.get("rel_path") or ""
    path = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in path.parents and path != root_resolved:
        raise MaterialError("invalid material path", status_code=500)
    return path


def read_material_bytes(settings: Settings, material: dict[str, Any]) -> bytes:
    path = material_path(settings, material)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MaterialError(f"material file missing: {exc}", status_code=410) from exc


def save_material(
    settings: Settings,
    *,
    filename: str,
    content_type: str,
    data: bytes,
    title: str = "",
    meta: dict[str, Any] | None = None,
    category_id: int | None = None,
    age_group_id: int | None = None,
    subject_id: int | None = None,
    source: str = "upload",
    source_path: str = "",
) -> tuple[dict[str, Any], bool]:
    """Store an uploaded material, returning ``(row, created)``.

    Files are content addressed: uploading identical bytes twice returns the
    existing row and does not duplicate storage.
    """
    if not data:
        raise MaterialError("empty upload", status_code=400)
    kind, normalized_type = _detect_kind(filename, content_type, data)
    if kind == "image" and len(data) > settings.image_max_mb * 1024 * 1024:
        raise MaterialError(f"image too large (max {settings.image_max_mb} MB)", status_code=413)

    digest = sha256_bytes(data)
    existing = get_material(settings, digest)
    if existing:
        return existing, False

    suffix = _extension_for(normalized_type, filename)
    rel_path = f"{digest}{suffix}"
    root = _root_for(settings, kind)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / rel_path
    temporary = root / f".{digest}.part"
    temporary.write_bytes(data)
    temporary.replace(destination)

    now = iso(utcnow())
    with session(settings) as conn:
        # Re-check inside the write transaction to survive concurrent uploads.
        row = conn.execute("SELECT * FROM materials WHERE sha256 = ?", (digest,)).fetchone()
        if row:
            return dict(row), False
        cursor = conn.execute(
            """
            INSERT INTO materials(sha256, kind, title, filename, content_type,
                                  size_bytes, rel_path, status, meta_json,
                                  category_id, age_group_id, subject_id, source, source_path,
                                  created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                digest,
                kind,
                title.strip() or filename,
                filename,
                normalized_type,
                len(data),
                rel_path,
                json_dumps(meta or {}),
                category_id,
                age_group_id,
                subject_id,
                source,
                source_path,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row), True


def upsert_text_material(
    settings: Settings,
    *,
    title: str,
    text: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store admin-entered text (future text/math question source)."""
    material, _ = save_material(
        settings,
        filename=f"{title or 'note'}.txt",
        content_type="text/plain",
        data=text.encode("utf-8"),
        title=title,
        meta=meta,
    )
    return material


def material_public_dict(
    settings: Settings, material: dict[str, Any], session_id: str | None = None
) -> dict[str, Any]:
    suffix = f"?s={session_id}" if session_id else ""
    url = f"{settings.image_url_prefix}/{material['sha256']}{suffix}"
    return {
        "id": material["id"],
        "sha256": material["sha256"],
        "kind": material["kind"],
        "title": material["title"],
        "filename": material["filename"],
        "contentType": material["content_type"],
        "sizeBytes": material["size_bytes"],
        "url": url,
        "categoryId": material.get("category_id"),
        "ageGroupId": material.get("age_group_id"),
        "subjectId": material.get("subject_id"),
        "source": material.get("source", "upload"),
        "sourcePath": material.get("source_path", ""),
        "createdAt": material["created_at"],
    }


def admin_material_dict(settings: Settings, material: dict[str, Any]) -> dict[str, Any]:
    # Admin pages can be opened under any LAN name (192.168.x.x, mDNS, ...). Relative URLs keep
    # the admin cookie on the same origin as the page; TV question URLs still use PUBLIC_BASE_URL.
    public = material_public_dict(settings, material)
    public["url"] = f"/api/v1/images/{material['sha256']}"
    return {
        **public,
        "status": material["status"],
        "meta": material.get("meta_json", "{}"),
    }


def get_image_material(settings: Settings, image_id: str) -> dict[str, Any] | None:
    """Look up an image material by sha256 or by numeric material id."""
    material = get_material(settings, image_id)
    if material:
        return material
    if image_id.isdigit():
        candidate = get_material_by_id(settings, int(image_id))
        if candidate and candidate["kind"] == "image":
            return candidate
    return None
