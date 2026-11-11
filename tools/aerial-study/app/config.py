"""Configuration for the Aerial Study Guard NAS service.

All configuration comes from environment variables (optionally loaded from a
local ``.env`` file).  API keys are read **only** from the environment and are
never persisted to SQLite, returned by an API, or written to logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load a local .env for `python -m uvicorn ...` development runs.  Docker
# Compose injects the same variables directly.
try:  # pragma: no cover - python-dotenv is an optional convenience
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    _load_dotenv = None


def _load_env_file(path: str | None = None) -> None:
    """Load a simple KEY=VALUE .env file without overriding real env vars."""
    candidate = Path(path or os.environ.get("ENV_FILE") or ".env")
    if not candidate.is_file():
        return
    if _load_dotenv is not None:
        _load_dotenv(candidate, override=False)
        return
    # Minimal fallback parser so the service still works without python-dotenv.
    try:
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name, "").lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime settings, frozen for the lifetime of the app."""

    data_dir: Path
    images_dir: Path
    materials_dir: Path
    db_path: Path

    study_device_token: str = field(default="", repr=False)
    admin_password: str = field(default="", repr=False)
    admin_secret_key: str = field(default="", repr=False)
    admin_session_hours: int = 12
    admin_cookie_name: str = "study_admin"

    session_ttl_hours: int = 24
    questions_per_session: int = 5

    image_max_mb: int = 10

    asr_model: str = "small"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_language: str = "auto"
    asr_beam_size: int = 1
    asr_max_mb: int = 20
    asr_queue_size: int = 8
    asr_timeout_seconds: int = 120
    asr_pcm_sample_rate: int = 16000
    asr_pcm_channels: int = 1
    asr_pcm_sample_width: int = 2

    deepseek_api_key: str = field(default="", repr=False)
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    deepseek_auth_header: str = "Authorization"

    xiaomi_mimo_api_key: str = field(default="", repr=False)
    xiaomi_mimo_base_url: str = ""
    xiaomi_mimo_model: str = ""
    xiaomi_mimo_auth_header: str = "Authorization"

    ai_timeout_seconds: float = 60.0
    ai_max_tokens: int = 2048
    default_provider: str = "deepseek"
    ai_judge_enabled: bool = False

    public_base_url: str = ""
    scan_roots: str = ""
    log_level: str = "INFO"
    generation_inline: bool = False
    version: str = "0.1.0"

    @classmethod
    def from_env(cls, env_file: str | None = None) -> Settings:
        _load_env_file(env_file)
        data_dir = Path(_env("DATA_DIR", "/data")).expanduser()
        images_dir = Path(_env("IMAGES_DIR", str(data_dir / "images"))).expanduser()
        materials_dir = Path(_env("MATERIALS_DIR", str(data_dir / "materials"))).expanduser()
        db_path = Path(_env("DB_PATH", str(data_dir / "study.db"))).expanduser()

        settings = cls(
            data_dir=data_dir,
            images_dir=images_dir,
            materials_dir=materials_dir,
            db_path=db_path,
            study_device_token=_env("STUDY_DEVICE_TOKEN"),
            admin_password=_env("ADMIN_PASSWORD"),
            admin_secret_key=_env("ADMIN_SECRET_KEY"),
            admin_session_hours=_env_int("ADMIN_SESSION_HOURS", 12),
            admin_cookie_name=_env("ADMIN_COOKIE_NAME", "study_admin"),
            session_ttl_hours=_env_int("SESSION_TTL_HOURS", 24),
            questions_per_session=max(1, _env_int("QUESTIONS_PER_SESSION", 5)),
            image_max_mb=max(1, _env_int("IMAGE_MAX_MB", 10)),
            asr_model=_env("ASR_MODEL", "small") or "small",
            asr_device=_env("ASR_DEVICE", "cpu") or "cpu",
            asr_compute_type=_env("ASR_COMPUTE_TYPE", "int8") or "int8",
            asr_language=_env("ASR_LANGUAGE", "auto") or "auto",
            asr_beam_size=max(1, _env_int("ASR_BEAM_SIZE", 1)),
            asr_max_mb=max(1, _env_int("ASR_MAX_MB", 20)),
            asr_queue_size=max(1, _env_int("ASR_QUEUE_SIZE", 8)),
            asr_timeout_seconds=max(5, _env_int("ASR_TIMEOUT_SECONDS", 120)),
            asr_pcm_sample_rate=_env_int("ASR_PCM_SAMPLE_RATE", 16000),
            asr_pcm_channels=_env_int("ASR_PCM_CHANNELS", 1),
            asr_pcm_sample_width=_env_int("ASR_PCM_SAMPLE_WIDTH", 2),
            deepseek_api_key=_env("DEEPSEEK_API_KEY"),
            deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
            deepseek_auth_header=_env("DEEPSEEK_AUTH_HEADER", "Authorization"),
            xiaomi_mimo_api_key=_env("XIAOMI_MIMO_API_KEY"),
            xiaomi_mimo_base_url=_env("XIAOMI_MIMO_BASE_URL"),
            xiaomi_mimo_model=_env("XIAOMI_MIMO_MODEL"),
            xiaomi_mimo_auth_header=_env("XIAOMI_MIMO_AUTH_HEADER", "Authorization"),
            ai_timeout_seconds=_env_float("AI_TIMEOUT_SECONDS", 60.0),
            ai_max_tokens=max(64, _env_int("AI_MAX_TOKENS", 2048)),
            default_provider=_env("AI_PROVIDER", "deepseek") or "deepseek",
            ai_judge_enabled=_env_bool("AI_JUDGE_ENABLED", False),
            public_base_url=_env("PUBLIC_BASE_URL").rstrip("/"),
            scan_roots=_env("STUDY_SCAN_ROOTS", ""),
            log_level=_env("LOG_LEVEL", "INFO") or "INFO",
            generation_inline=_env_bool("GENERATION_INLINE", False),
            version=_env("STUDY_VERSION", "0.1.0") or "0.1.0",
        )
        return settings

    def prepare_dirs(self) -> None:
        for directory in (self.data_dir, self.images_dir, self.materials_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_password)

    @property
    def device_auth_enabled(self) -> bool:
        return bool(self.study_device_token)

    @property
    def image_url_prefix(self) -> str:
        return f"{self.public_base_url}/api/v1/images" if self.public_base_url else "/api/v1/images"
