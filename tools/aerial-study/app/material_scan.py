"""Scan an allow-listed NAS directory into the material library."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from .config import Settings
from .materials import IMAGE_EXTENSIONS, MaterialError, save_material
from .taxonomy import age_group_exists, parse_category, subject_exists

TEXT_EXTENSIONS = {".txt", ".md"}
PDF_EXTENSIONS = {".pdf"}
MAX_FILES = 500


class ScanError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def roots(settings: Settings) -> list[Path]:
    values = [value.strip() for value in (settings.scan_roots or "").replace(";", ":").split(":") if value.strip()]
    out: list[Path] = []
    for value in values:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            out.append(path)
    return out


def resolve_root(settings: Settings, raw: str) -> Path:
    candidate = Path(raw).expanduser().resolve()
    for root in roots(settings):
        if candidate == root or root in candidate.parents:
            return candidate
    raise ScanError("directory is not in STUDY_SCAN_ROOTS", status_code=403)


def scan_directory(
    settings: Settings,
    *,
    root: str,
    category_id: int | None = None,
    age_group_id: int | None = None,
    subject_id: int | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    base = resolve_root(settings, root)
    if not age_group_exists(settings, age_group_id):
        raise ScanError("age group not found", status_code=404)
    if not subject_exists(settings, subject_id):
        raise ScanError("subject not found", status_code=404)
    if category_id is not None:
        parse_category(settings, category_id)
    files = [p for p in (base.rglob("*") if recursive else base.glob("*")) if p.is_file() and not p.is_symlink()]
    files = files[:MAX_FILES + 1]
    if len(files) > MAX_FILES:
        raise ScanError(f"too many files (max {MAX_FILES})", status_code=413)
    created = 0
    existing = 0
    errors: list[dict[str, str]] = []
    for path in files:
        suffix = path.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS | TEXT_EXTENSIONS | PDF_EXTENSIONS:
            continue
        try:
            data = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            _, is_new = save_material(
                settings,
                filename=path.name,
                content_type=content_type,
                data=data,
                title=path.stem,
                category_id=category_id,
                age_group_id=age_group_id,
                subject_id=subject_id,
                source="scan",
                source_path=str(path),
            )
            if is_new:
                created += 1
            else:
                existing += 1
        except (OSError, MaterialError) as exc:
            errors.append({"path": str(path), "error": getattr(exc, "message", str(exc))[:300]})
    return {
        "root": str(base),
        "created": created,
        "existing": existing,
        "errors": errors,
        "scanned": len(files),
    }
