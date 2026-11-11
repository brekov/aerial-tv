"""Optional MiMo audio judge: audio + transcript -> pronunciation/feedback JSON.

This is deliberately best-effort.  It never replaces the text gate; callers
fall back to the existing judge when the provider rejects audio or returns
malformed output.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from .config import Settings
from .providers import ProviderError, get_provider_config
from .util import redact

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 1_500_000


def _clamp(value: Any, low: int = 0, high: int = 100) -> int | None:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def _normalize(data: dict[str, Any]) -> dict[str, Any] | None:
    verdict = str(data.get("verdict") or data.get("decision") or "").strip().lower()
    if verdict in {"pass", "correct", "good", "yes", "accepted", "accept"}:
        verdict = "correct"
    elif verdict in {"retry", "near", "near_miss", "almost"}:
        verdict = "near"
    elif verdict in {"fail", "wrong", "incorrect", "no"}:
        verdict = "wrong"
    else:
        verdict = "near"

    pronunciation: dict[str, Any] = {}
    for key in ("overall", "accuracy", "fluency", "completeness", "prosody"):
        value = _clamp(data.get(key))
        if value is not None:
            pronunciation[key] = value
    if not pronunciation:
        return None

    phonemes = data.get("phonemes")
    if not isinstance(phonemes, list):
        phonemes = []
    cleaned_phonemes = []
    for item in phonemes[:32]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("phoneme") or item.get("symbol") or item.get("sound") or "").strip()
        score = _clamp(item.get("score"))
        if symbol and score is not None:
            cleaned_phonemes.append({"phoneme": symbol, "score": score})
    pronunciation["phonemes"] = cleaned_phonemes

    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    issues = data.get("issues")
    if not isinstance(issues, list):
        issues = []
    return {
        "verdict": verdict,
        "confidence": round(confidence, 3),
        "heard": str(data.get("heard") or "").strip()[:200],
        "issues": [str(value)[:120] for value in issues[:8]],
        "feedback": str(data.get("feedback") or "").strip()[:300],
        "pronunciation": pronunciation,
    }


def judge_audio(
    settings: Settings,
    *,
    reference: str,
    word: str,
    audio: bytes | None,
) -> dict[str, Any] | None:
    """Ask MiMo V2.6 to judge the recording and estimate pronunciation.

    Returns None on any provider/format failure; the caller must keep the text
    result and continue the quiz.
    """
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        return None
    try:
        config = get_provider_config(settings, "xiaomi_mimo")
    except ProviderError:
        return None
    if not config.configured:
        return None

    encoded = base64.b64encode(audio).decode("ascii")
    prompt = (
        "You are a child-friendly English pronunciation judge. "
        "Listen to the attached recording and compare it with the target word.\n"
        f"Target word: {word}\n"
        f"Accepted answers: {reference}\n"
        "Return ONLY a JSON object with this shape:\n"
        '{"verdict":"correct|near|wrong", "confidence":0.0, '
        '"heard":"what you heard", "overall":0, "accuracy":0, "fluency":0, '
        '"completeness":0, "prosody":0, '
        '"phonemes":[{"phoneme":"...", "score":0}], '
        '"issues":["short issue"], "feedback":"short child-friendly feedback"}\n'
        "Scores are 0-100. Be strict about the target consonants and vowels, "
        "but do not penalise a natural child accent. Do not return markdown."
    )
    messages = [
        {"role": "system", "content": "Reply with strict JSON only."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "input_audio",
                    "input_audio": {"data": f"data:audio/wav;base64,{encoded}"},
                },
            ],
        },
    ]
    body = {
        "model": config.model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 500,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=min(config.timeout, 10.0)) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                json=body,
                headers={"Content-Type": "application/json", **config.auth_headers()},
            )
        if response.status_code >= 400:
            logger.info("MiMo audio judge HTTP %s: %s", response.status_code, redact(response.text[:300]))
            return None
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            return None
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        return _normalize(json.loads(cleaned[start : end + 1]))
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.info("MiMo audio judge unavailable: %s", redact(str(exc)))
        return None
