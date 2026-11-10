"""Small shared helpers: time, hashing, text normalisation, redaction."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\s\u3000-\u303f\uff00-\uffef!-/:-@\[-`{-~]+")
_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|authorization|token|password|secret)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s\"',}]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/=-]+)")
_KEYLIKE_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{6,})\b")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_ZH_EDGE_FILLERS = ("嗯", "啊", "呃", "额", "这个", "那个", "请")


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


def _strip_edge_fillers(text: str) -> str:
    """Drop common spoken fillers only at the edges, never inside a word."""
    value = text
    changed = True
    while changed and value:
        changed = False
        for filler in _ZH_EDGE_FILLERS:
            if value.startswith(filler) and len(value) > len(filler):
                value = value[len(filler):]
                changed = True
            if value.endswith(filler) and len(value) > len(filler):
                value = value[:-len(filler)]
                changed = True
    return value


def _pinyin(value: str) -> str:
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return ""
    return "".join(lazy_pinyin(value, errors=lambda chars: list(chars)))


def _edit_distance(left: str, right: str) -> int:
    """Small Levenshtein distance; these answers are only a few characters."""
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, lchar in enumerate(left, 1):
        current = [i]
        for j, rchar in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (lchar != rchar),
            ))
        previous = current
    return previous[-1]


def match_answer(accepted: list[str], transcript: str) -> tuple[bool, str, dict[str, Any]]:
    """Forgiving but bounded matching for a short spoken answer.

    Exact normalized aliases first. For CJK targets a tone-less pinyin match
    handles common ASR homophones; for Latin targets only a one-edit near miss
    with high similarity is accepted. Short words stay strict.
    """
    normalized = normalize_answer(transcript)
    candidate = _strip_edge_fillers(normalized)
    detail: dict[str, Any] = {"transcriptNormalized": normalized, "acceptedCount": len(accepted)}
    if not candidate:
        return False, "exact", detail
    if candidate in accepted:
        return True, "exact", detail

    for target in accepted:
        target_clean = _strip_edge_fillers(target)
        if not target_clean:
            continue
        if _CJK_RE.search(target_clean):
            target_pinyin = _pinyin(target_clean)
            candidate_pinyin = _pinyin(candidate)
            if target_pinyin and target_pinyin == candidate_pinyin:
                detail.update({
                    "pinyinTarget": target_pinyin,
                    "pinyinTranscript": candidate_pinyin,
                })
                return True, "pinyin", detail
            continue

        # Latin words: no fuzzy matching for very short targets (cat, dog, ...).
        if len(target_clean) < 4:
            continue
        if abs(len(target_clean) - len(candidate)) > 1:
            continue
        ratio = SequenceMatcher(None, target_clean, candidate).ratio()
        distance = _edit_distance(target_clean, candidate)
        if ratio >= 0.82 and distance <= 1:
            detail.update({"fuzzyTarget": target_clean, "fuzzyRatio": round(ratio, 3), "editDistance": distance})
            return True, "fuzzy", detail

    return False, "exact", detail


def _phones(word: str) -> list[list[str]]:
    """CMU pronunciation variants without stress digits, when the package is present."""
    try:
        import pronouncing
    except ImportError:
        return []
    try:
        raw = pronouncing.phones_for_word(word.lower())
    except Exception:
        return []
    return [re.sub(r"\d", "", line).split() for line in raw if line.strip()]


def _candidate_words(value: str) -> list[str]:
    return re.findall(r"[a-z]+", value.lower())


def _phone_distance(left: list[str], right: list[str]) -> int:
    if not left or not right:
        return 99
    previous = list(range(len(right) + 1))
    for i, lvalue in enumerate(left, 1):
        current = [i]
        for j, rvalue in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (lvalue != rvalue),
            ))
        previous = current
    return previous[-1]


def match_answer_full(
    accepted: list[str], transcript: str
) -> tuple[bool, bool, str, dict[str, Any]]:
    """Return (correct, retry, method, detail).

    Correct is a confident pass. Retry is a near miss that should ask the child
    to repeat without resetting the five-question run. Short Latin words remain
    strict; only words of at least four letters get phonetic leniency.
    """
    normalized = normalize_answer(transcript)
    candidate = _strip_edge_fillers(normalized)
    detail: dict[str, Any] = {"transcriptNormalized": normalized, "acceptedCount": len(accepted)}
    if not candidate:
        return False, False, "exact", detail
    if candidate in accepted:
        return True, False, "exact", detail

    for target in accepted:
        target_clean = _strip_edge_fillers(target)
        if not target_clean:
            continue
        if _CJK_RE.search(target_clean):
            target_pinyin = _pinyin(target_clean)
            candidate_pinyin = _pinyin(candidate)
            if target_pinyin and target_pinyin == candidate_pinyin:
                detail.update({
                    "pinyinTarget": target_pinyin,
                    "pinyinTranscript": candidate_pinyin,
                })
                return True, False, "pinyin", detail
            if target_pinyin and candidate_pinyin:
                pinyin_distance = _edit_distance(target_pinyin, candidate_pinyin)
                if pinyin_distance == 1:
                    detail.update({
                        "pinyinTarget": target_pinyin,
                        "pinyinTranscript": candidate_pinyin,
                        "pinyinDistance": pinyin_distance,
                        "retry": True,
                    })
                    return False, True, "near_miss", detail
            continue

        if len(target_clean) < 4:
            continue

        # Keep the existing spelling fuzzy rule for typos and plurals.
        if abs(len(target_clean) - len(candidate)) <= 1:
            ratio = SequenceMatcher(None, target_clean, candidate).ratio()
            text_distance = _edit_distance(target_clean, candidate)
            if ratio >= 0.82 and text_distance <= 1:
                detail.update({
                    "fuzzyTarget": target_clean,
                    "fuzzyRatio": round(ratio, 3),
                    "editDistance": text_distance,
                })
                return True, False, "fuzzy", detail

        # Compare pronunciation, not spelling, for the lion/line class of ASR errors.
        target_phones = _phones(target_clean)
        candidate_phones = []
        for word in _candidate_words(transcript):
            candidate_phones.extend(_phones(word))
        if not target_phones or not candidate_phones:
            continue
        best = 99
        for left in target_phones:
            for right in candidate_phones:
                best = min(best, _phone_distance(left, right))
        detail["phoneticDistance"] = best
        if best <= 1:
            return True, False, "phonetic", detail
        if best == 2:
            detail["retry"] = True
            return False, True, "near_miss", detail

    return False, False, "exact", detail


def match_answer(accepted: list[str], transcript: str) -> tuple[bool, str, dict[str, Any]]:
    """Backward-compatible wrapper used by older callers/tests."""
    correct, _retry, method, detail = match_answer_full(accepted, transcript)
    return correct, method, detail


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
