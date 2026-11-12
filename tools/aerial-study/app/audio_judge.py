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
    if verdict in {"no_speech", "nospeech", "silent", "silence", "no speech"}:
        verdict = "no_speech"
    elif verdict in {"pass", "correct", "good", "yes", "accepted", "accept"}:
        verdict = "correct"
    elif verdict in {"retry", "near", "near_miss", "almost"}:
        verdict = "near"
    elif verdict in {"fail", "wrong", "incorrect", "no"}:
        verdict = "wrong"
    else:
        verdict = "near"

    pronunciation: dict[str, Any] = {}
    raw_score = _clamp(data.get("score"))
    if raw_score is not None and "overall" not in data:
        data = {**data, "overall": raw_score}
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


def judge_repeat_audio(
    settings: Settings,
    *,
    word: str,
    letters: list[str],
    audio: bytes | None,
) -> dict[str, Any] | None:
    """One multimodal call for repeat-learning pronunciation.

    The model both hears the audio and scores the target word.  There is no
    ASR stage and no text judge in this path by design.
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
    spelling = " ".join(letters)
    prompt = (
        "你是儿童英语跟读评分老师。请听录音，判断孩子是否读出了目标单词，并评估发音。\n"
        f"目标单词: {word}\n"
        f"目标拼写: {spelling}\n"
        "只返回 JSON，不要 markdown：\n"
        '{"verdict":"correct|near|wrong|no_speech","score":0,'
        '"heard":"你听到的内容","overall":0,"accuracy":0,"fluency":0,'
        '"feedback":"一句简短中文反馈"}\n'
        "分数 0-100。孩子有口音不要过度扣分；完全没有读出目标词才判 wrong；"
        "没有有效语音则 verdict=no_speech。"
    )
    messages = [
        {"role": "system", "content": "只输出严格 JSON。"},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "input_audio", "input_audio": {"data": f"data:audio/wav;base64,{encoded}"}},
        ]},
    ]
    body = {
        "model": config.model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 300,
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
            logger.info("MiMo repeat judge HTTP %s", response.status_code)
            return None
        content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        cleaned = str(content).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").removeprefix("json").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        normalized = _normalize(json.loads(cleaned[start:end + 1]))
        if normalized is None:
            return None
        pronunciation = normalized.get("pronunciation") or {}
        score = int(pronunciation.get("overall", 0) or 0)
        if normalized.get("verdict") == "no_speech":
            score = 0
        return {
            "verdict": normalized.get("verdict", "near"),
            "score": max(0, min(100, score)),
            "heard": normalized.get("heard", ""),
            "feedback": normalized.get("feedback", ""),
            "pronunciation": pronunciation,
            "confidence": normalized.get("confidence", 0.5),
            "provider": config.name,
            "model": config.model,
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.info("MiMo repeat judge unavailable: %s", redact(str(exc)))
        return None
