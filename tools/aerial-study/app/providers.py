"""OpenAI-compatible AI providers (DeepSeek, Xiaomi MiMo) with pluggable config.

Provider *routing* settings (base URL, model, auth header name) can be changed
from the admin UI and are stored in SQLite.  API keys can only come from the
environment (``DEEPSEEK_API_KEY`` / ``XIAOMI_MIMO_API_KEY``); they are never
returned, stored, or logged.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .db import get_setting, read_session, session, set_setting
from .util import redact

PROVIDER_NAMES = ("deepseek", "xiaomi_mimo")
PROVIDER_LABELS = {"deepseek": "DeepSeek", "xiaomi_mimo": "Xiaomi MiMo"}

_SETTING_BASE_URL = "provider.{}.base_url"
_SETTING_MODEL = "provider.{}.model"
_SETTING_AUTH_HEADER = "provider.{}.auth_header"
_SETTING_DEFAULT = "ai.default_provider"
_SETTING_JUDGE = "ai.judge_enabled"


class ProviderError(Exception):
    """AI provider failure with a redacted, user-safe message."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    model: str
    auth_header: str
    api_key: str
    timeout: float
    max_tokens: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def auth_headers(self) -> dict[str, str]:
        if self.auth_header.lower() == "authorization":
            value = f"Bearer {self.api_key}"
        else:
            value = self.api_key
        return {self.auth_header: value}


def _env_defaults(settings: Settings, name: str) -> tuple[str, str, str, str]:
    if name == "deepseek":
        return (
            settings.deepseek_base_url,
            settings.deepseek_model,
            settings.deepseek_auth_header,
            settings.deepseek_api_key,
        )
    if name == "xiaomi_mimo":
        return (
            settings.xiaomi_mimo_base_url,
            settings.xiaomi_mimo_model,
            settings.xiaomi_mimo_auth_header,
            settings.xiaomi_mimo_api_key,
        )
    raise ProviderError(f"unknown provider: {name}", status_code=400)


def _override(settings: Settings, conn: Any, key: str, default: str) -> str:
    value = get_setting(conn, key, "")
    return value or default


def get_provider_config(settings: Settings, name: str | None = None) -> ProviderConfig:
    name = (name or default_provider(settings)).strip().lower()
    if name not in PROVIDER_NAMES:
        raise ProviderError(
            f"unknown provider '{name}' (choose: {', '.join(PROVIDER_NAMES)})",
            status_code=400,
        )
    env_base, env_model, env_header, api_key = _env_defaults(settings, name)
    with read_session(settings) as conn:
        base_url = _override(settings, conn, _SETTING_BASE_URL.format(name), env_base)
        model = _override(settings, conn, _SETTING_MODEL.format(name), env_model)
        auth_header = _override(settings, conn, _SETTING_AUTH_HEADER.format(name), env_header)
    return ProviderConfig(
        name=name,
        base_url=base_url.strip().rstrip("/"),
        model=model.strip(),
        auth_header=(auth_header or "Authorization").strip(),
        api_key=api_key.strip(),
        timeout=settings.ai_timeout_seconds,
        max_tokens=settings.ai_max_tokens,
    )


def default_provider(settings: Settings) -> str:
    with read_session(settings) as conn:
        name = get_setting(conn, _SETTING_DEFAULT, "") or settings.default_provider
    name = (name or "deepseek").strip().lower()
    return name if name in PROVIDER_NAMES else "deepseek"


def ai_judge_enabled(settings: Settings) -> bool:
    with read_session(settings) as conn:
        value = get_setting(conn, _SETTING_JUDGE, "")
    if value == "":
        return settings.ai_judge_enabled
    return value.lower() in {"1", "true", "yes", "on"}


def provider_status(settings: Settings) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    with read_session(settings) as conn:
        for name in PROVIDER_NAMES:
            env_base, env_model, env_header, api_key = _env_defaults(settings, name)
            base_url = _override(settings, conn, _SETTING_BASE_URL.format(name), env_base)
            model = _override(settings, conn, _SETTING_MODEL.format(name), env_model)
            auth_header = _override(settings, conn, _SETTING_AUTH_HEADER.format(name), env_header)
            providers[name] = {
                "name": name,
                "label": PROVIDER_LABELS[name],
                "baseUrl": base_url,
                "model": model,
                "authHeader": auth_header or "Authorization",
                "hasApiKey": bool(api_key),
                "configured": bool(api_key and base_url and model),
                "keySource": "env" if api_key else "missing",
            }
        return {
            "providers": providers,
            "defaultProvider": default_provider(settings),
            "aiJudgeEnabled": ai_judge_enabled(settings),
        }


def update_provider_settings(
    settings: Settings,
    name: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    auth_header: str | None = None,
    default: str | None = None,
    ai_judge_enabled: bool | None = None,
) -> dict[str, Any]:
    name = name.strip().lower()
    if name not in PROVIDER_NAMES:
        raise ProviderError(
            f"unknown provider '{name}' (choose: {', '.join(PROVIDER_NAMES)})",
            status_code=400,
        )
    if base_url is not None:
        base_url = base_url.strip().rstrip("/")
        if base_url and not re.match(r"^https?://[^\s]+$", base_url):
            raise ProviderError("baseUrl must be an http(s) URL", status_code=400)
        if base_url:
            _validate_public_url_syntax(base_url)
    if auth_header is not None:
        auth_header = auth_header.strip()
        if auth_header and not re.match(r"^[A-Za-z0-9-]{1,64}$", auth_header):
            raise ProviderError("invalid auth header name", status_code=400)
    with session(settings) as conn:
        if base_url is not None:
            set_setting(conn, _SETTING_BASE_URL.format(name), base_url)
        if model is not None:
            set_setting(conn, _SETTING_MODEL.format(name), model.strip())
        if auth_header is not None:
            set_setting(conn, _SETTING_AUTH_HEADER.format(name), auth_header)
        if default is not None:
            default = default.strip().lower()
            if default not in PROVIDER_NAMES:
                raise ProviderError("invalid default provider", status_code=400)
            set_setting(conn, _SETTING_DEFAULT, default)
        if ai_judge_enabled is not None:
            set_setting(conn, _SETTING_JUDGE, "1" if ai_judge_enabled else "0")
    # Never echo API keys; provider_status only exposes hasApiKey.
    return provider_status(settings)


def _validate_public_url_syntax(url: str) -> None:
    """Reject obviously local/loopback destinations to reduce SSRF risk.

    The admin is trusted, but this service is LAN-reachable; keep the mistake
    surface small.  Allow private LAN hosts because self-hosted gateways are a
    valid use case, only block link-local metadata endpoints.
    """
    lowered = url.lower()
    if lowered.startswith(("http://169.254.", "http://metadata.", "http://100.100.100.200")):
        raise ProviderError("baseUrl host is not allowed", status_code=400)


def _chat(
    config: ProviderConfig,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    if not config.api_key:
        raise ProviderError(
            f"provider '{config.name}' is not configured: set "
            f"{config.name.upper()}_API_KEY in .env",
            status_code=503,
        )
    if not config.base_url or not config.model:
        raise ProviderError(f"provider '{config.name}' is missing baseURL/model", status_code=503)
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or config.max_tokens,
        "stream": False,
    }
    headers = {"Content-Type": "application/json", **config.auth_headers()}
    url = f"{config.base_url}/chat/completions"
    try:
        with httpx.Client(timeout=config.timeout) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderError(f"provider '{config.name}' request failed: {redact(str(exc))}") from exc
    if response.status_code >= 400:
        body = redact(response.text[:500])
        raise ProviderError(
            f"provider '{config.name}' returned HTTP {response.status_code}: {body}"
        )
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"provider '{config.name}' returned an unexpected response") from exc
    if isinstance(content, list):  # some gateways return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ProviderError(f"provider '{config.name}' returned an empty answer")
    return content.strip()


def _vision_messages(prompt: str, image_bytes: bytes, mime_type: str) -> list[dict[str, Any]]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return [
        {
            "role": "system",
            "content": (
                "You create high-quality vocabulary quiz material for children. "
                "Always reply with strict JSON and nothing else."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        },
    ]


def _extract_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    # Fall back to the outermost JSON array/object in the reply.
    array_start, array_end = cleaned.find("["), cleaned.rfind("]")
    if array_start != -1 and array_end > array_start:
        try:
            return json.loads(cleaned[array_start : array_end + 1])
        except ValueError:
            pass
    obj_start, obj_end = cleaned.find("{"), cleaned.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        try:
            return json.loads(cleaned[obj_start : obj_end + 1])
        except ValueError:
            pass
    raise ProviderError("AI reply was not valid JSON")


def _word_image_prompt(lang: str, count: int) -> str:
    language = "Chinese" if lang == "zh" else "English"
    return (
        f"Look at the attached image and create {count} vocabulary questions "
        f"in {language}. Each question shows this image and asks for one word "
        "that names the main object or action in the image. Use child-friendly, "
        "unambiguous words. Return a JSON array with exactly this shape:\n"
        '{"prompt": "What is this?", "answer": "apple", '
        '"explanation": "It is a red fruit.", "difficulty": 1}\n'
        f"Return exactly {count} distinct objects. Do not use markdown. "
        "The answer must be a single word unless the object needs two words."
    )


def generate_word_image_questions(
    settings: Settings,
    *,
    provider_name: str | None = None,
    image_bytes: bytes,
    mime_type: str,
    lang: str,
    count: int,
) -> tuple[list[dict[str, Any]], ProviderConfig]:
    config = get_provider_config(settings, provider_name)
    raw = _chat(
        config,
        _vision_messages(_word_image_prompt(lang, count), image_bytes, mime_type),
        temperature=0.4,
    )
    data = _extract_json(raw)
    items: Any = data
    if isinstance(data, dict):
        items = data.get("questions") or data.get("items") or data.get("data")
    if not isinstance(items, list):
        raise ProviderError("AI reply did not contain a question list")

    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not prompt or not answer:
            continue
        key = prompt.lower()
        if key in seen:
            continue
        seen.add(key)
        difficulty = item.get("difficulty", 1)
        try:
            difficulty = max(1, min(5, int(difficulty)))
        except (TypeError, ValueError):
            difficulty = 1
        questions.append(
            {
                "prompt": prompt,
                "answer": answer,
                "explanation": str(item.get("explanation") or "").strip(),
                "difficulty": difficulty,
            }
        )
        if len(questions) >= count:
            break
    if not questions:
        raise ProviderError("AI reply contained no usable questions")
    return questions, config


def judge_answer_ai(
    settings: Settings,
    *,
    question_prompt: str,
    reference_answer: str,
    transcript: str,
) -> bool | None:
    """Optional text judging fallback.  Returns None when AI is unavailable."""
    if not ai_judge_enabled(settings):
        return None
    try:
        config = get_provider_config(settings, None)
    except ProviderError:
        return None
    if not config.configured:
        return None
    messages = [
        {
            "role": "system",
            "content": (
                "You grade a student's spoken answer. The reference answer may "
                "list alternatives. Ignore case, punctuation and articles. "
                "Reply with exactly YES or NO."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {question_prompt}\n"
                f"Reference answer(s): {reference_answer}\n"
                f"Student answer: {transcript}\n"
                "Is the student answer correct?"
            ),
        },
    ]
    try:
        raw = _chat(config, messages, temperature=0.0, max_tokens=8)
    except ProviderError:
        return None
    return raw.strip().upper().startswith("YES")
