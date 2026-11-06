"""Small shared helpers: time, hashing, text normalisation, redaction."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\s\u3000-\u303f\uff00-\uffef!-/:-@\[-`{-~]+")
_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|authorization|token|password|secret)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s\"',}]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/=-]+)")
_KEYLIKE_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{6,})\b")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="seconds")


def iso_from_now(**delta: float) -> str:
    return iso(utcnow() + timedelta(**delta))


def parse_iso(value: str) -> datetime:
    """Parse an ISO timestamp; treat naive values as UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_id() -> str:
    return secrets.token_hex(16)


def normalize_answer(value: str) -> str:
    """Normalise an answer for forgiving exact matching.

    Lowercase, Unicode NFKC, strip whitespace/punctuation (CJK punctuation
    included) so "Hello, world!" == "hello world" and "苹果。" == "苹果".
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).strip().lower()
    text = _PUNCT_RE.sub("", text)
    return text


def split_accepted_answers(answer: str) -> list[str]:
    """Accepted answers may be separated by ``|`` or newlines."""
    parts = re.split(r"[|\n]", answer or "")
    values = [normalize_answer(part) for part in parts]
    return [value for value in values if value]


def epoch_seconds(value: str) -> int:
    return int(parse_iso(value).timestamp())


def mask_secret(value: str) -> bool:
    return bool(value)


def redact(text: str) -> str:
    """Best-effort redaction before a provider error is stored/logged."""
    if not text:
        return text
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)} ***", text)
    text = _SECRET_RE.sub(lambda m: f"{m.group(1)}***", text)
    return _KEYLIKE_RE.sub("***", text)


def safe_json_loads(value: str | None, default: Any) -> Any:
    import json

    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
