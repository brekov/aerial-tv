"""AI question generation jobs.

A job is created synchronously (so the admin immediately gets an id), then runs
on a single background thread.  Generated questions are always inserted as
``draft`` — nothing is auto-activated.  Each job's status/error is persisted so
failures are visible in the admin UI.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import Settings
from .db import read_session, session
from .materials import (
    get_image_material,
    read_material_bytes,
)
from .providers import (
    ProviderError,
    generate_word_image_questions,
    get_provider_config,
)
from .questions import QuestionError, create_question, question_admin_dict
from .util import iso, json_dumps, new_id, redact, safe_json_loads, utcnow

logger = logging.getLogger(__name__)


class GenerationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return iso(utcnow())


class GenerationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="generation")
        self._closed = False
        self._lock = threading.Lock()

    # -- job API -----------------------------------------------------------

    def create_job(
        self,
        *,
        material_id: str,
        provider: str | None = None,
        lang: str = "zh",
        count: int = 5,
        requested_by: str = "admin",
    ) -> dict[str, Any]:
        material = get_image_material(self.settings, str(material_id))
        if not material:
            raise GenerationError("image material not found", status_code=404)
        if material["kind"] != "image":
            raise GenerationError(
                "only image materials can be used for word_image generation",
                status_code=400,
            )
        lang = (lang or "zh").strip().lower()
        if lang not in {"zh", "en"}:
            raise GenerationError("lang must be 'zh' or 'en'", status_code=400)
        try:
            count = int(count)
        except (TypeError, ValueError):
            raise GenerationError("count must be an integer", status_code=400) from None
        count = max(1, min(count, 20))
        # A word-image card already carries exactly one target word. Generating several
        # questions from the same card would repeat the same flashcard; keep one.
        count = 1

        provider_name = (provider or "").strip().lower()
        try:
            config = get_provider_config(self.settings, provider_name or None)
        except ProviderError as exc:
            raise GenerationError(exc.message, status_code=exc.status_code) from exc
        provider_name = config.name

        job_id = new_id()
        now = _now()
        error = ""
        status_value = "pending"
        if not config.configured:
            status_value = "failed"
            error = (
                f"provider '{config.name}' is not configured: set "
                f"{config.name.upper()}_API_KEY (and base URL/model) in .env"
            )
        with session(self.settings) as conn:
            conn.execute(
                """
                INSERT INTO generation_jobs(
                    id, provider, model, material_id, kind, lang, count,
                    status, error, result_json, requested_by, created_at,
                    started_at, finished_at)
                VALUES(?, ?, ?, ?, 'word_image', ?, ?, ?, ?, '{}', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    provider_name,
                    config.model,
                    material["sha256"],
                    lang,
                    count,
                    status_value,
                    error,
                    requested_by,
                    now,
                    now if status_value == "failed" else None,
                    now if status_value == "failed" else None,
                ),
            )
        if status_value == "failed":
            return self.get_job(job_id)  # type: ignore[return-value]

        if self.settings.generation_inline:
            self.run_job(job_id)
        else:
            self._executor.submit(self.run_job, job_id)
        return self.get_job(job_id)  # type: ignore[return-value]

    def run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job or job["status"] not in {"pending", "running"}:
            return
        started_at = _now()
        with session(self.settings) as conn:
            conn.execute(
                """
                UPDATE generation_jobs
                SET status = 'running', started_at = ?, error = ''
                WHERE id = ?
                """,
                (started_at, job_id),
            )
        try:
            material = get_image_material(self.settings, str(job["materialId"]))
            if not material:
                raise GenerationError("image material disappeared", status_code=410)
            image_bytes = read_material_bytes(self.settings, material)
            items, config = generate_word_image_questions(
                self.settings,
                provider_name=job["provider"],
                image_bytes=image_bytes,
                mime_type=material["content_type"],
                lang=job["lang"],
                count=int(job["count"]),
            )
            created: list[dict[str, Any]] = []
            for item in items:
                question = create_question(
                    self.settings,
                    prompt=item["prompt"],
                    answer=item["answer"],
                    question_type="word_image",
                    lang=job["lang"],
                    image_id=material["sha256"],
                    explanation=item.get("explanation", ""),
                    difficulty=item.get("difficulty", 1),
                    status_value="draft",
                    source="ai",
                    meta={
                        "generationJobId": job_id,
                        "provider": config.name,
                        "model": config.model,
                    },
                    changed_by=f"ai:{config.name}",
                    change_note=f"generated by {config.name}/{config.model}",
                )
                created.append(question_admin_dict(self.settings, question))
            result = {
                "questionIds": [question["id"] for question in created],
                "questions": created,
                "provider": config.name,
                "model": config.model,
            }
            with session(self.settings) as conn:
                conn.execute(
                    """
                    UPDATE generation_jobs
                    SET status = 'succeeded', result_json = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (json_dumps(result), _now(), job_id),
                )
            logger.info(
                "generation job %s succeeded: %d draft question(s) via %s",
                job_id,
                len(created),
                config.name,
            )
        except (ProviderError, QuestionError, GenerationError) as exc:
            message = redact(getattr(exc, "message", str(exc)))
            self._fail_job(job_id, message)
            logger.warning("generation job %s failed: %s", job_id, message)
        except Exception as exc:  # pragma: no cover - defensive
            message = redact(f"unexpected error: {type(exc).__name__}: {exc}")
            self._fail_job(job_id, message)
            logger.exception("generation job %s crashed", job_id)

    def _fail_job(self, job_id: str, message: str) -> None:
        with session(self.settings) as conn:
            conn.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed', error = ?, finished_at = ?
                WHERE id = ?
                """,
                (message[:2000], _now(), job_id),
            )

    # -- queries -----------------------------------------------------------

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with read_session(self.settings) as conn:
            row = conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with read_session(self.settings) as conn:
            rows = conn.execute(
                "SELECT * FROM generation_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_job_dict(row) for row in rows]

    def shutdown(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._executor.shutdown(wait=False, cancel_futures=True)


def _job_dict(row: Any) -> dict[str, Any]:
    result = safe_json_loads(row["result_json"], {})
    return {
        "id": row["id"],
        "provider": row["provider"],
        "model": row["model"],
        "materialId": row["material_id"],
        "kind": row["kind"],
        "lang": row["lang"],
        "count": row["count"],
        "status": row["status"],
        "error": row["error"],
        "result": result,
        "questionIds": result.get("questionIds", []),
        "requestedBy": row["requested_by"],
        "createdAt": row["created_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
    }
