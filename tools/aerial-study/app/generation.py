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
    generate_choice_questions,
    generate_word_image_questions,
    get_provider_config,
)
from .taxonomy import question_type
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
        material_id: str | None,
        material_ids: list[str] | None = None,
        provider: str | None = None,
        lang: str = "zh",
        count: int = 5,
        requested_by: str = "admin",
        question_type_code: str = "word_image",
        age_group_id: int | None = None,
        subject_id: int | None = None,
        answer_mode: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        type_info = question_type(self.settings, question_type_code)
        if not type_info:
            raise GenerationError("unknown question type", status_code=400)
        requires_image = bool(type_info.get("requires_image")) or question_type_code == "word_image"
        requested_ids = material_ids or ([material_id] if material_id else [])
        materials: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for requested in requested_ids:
            material = get_image_material(self.settings, str(requested))
            if not material:
                raise GenerationError(f"material not found: {requested}", status_code=404)
            if material["kind"] != "image":
                raise GenerationError("material must be an image", status_code=400)
            if material["sha256"] not in seen_ids:
                seen_ids.add(material["sha256"])
                materials.append(material)
        if requires_image and not materials:
            raise GenerationError("this question type requires an image material", status_code=400)
        lang = (lang or "zh").strip().lower()
        if lang not in {"zh", "en"}:
            raise GenerationError("lang must be 'zh' or 'en'", status_code=400)
        try:
            count = int(count)
        except (TypeError, ValueError):
            raise GenerationError("count must be an integer", status_code=400) from None
        count = max(1, min(count, 20))
        # One selected image produces one question. With several images, count is the
        # number of images rather than a request for several questions per image.
        per_image_count = 1 if len(materials) > 1 else count
        if question_type_code == "word_image":
            per_image_count = 1
        effective_count = len(materials) if len(materials) > 1 else per_image_count

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
                    started_at, finished_at, question_type, age_group_id,
                    subject_id, answer_mode, params_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    provider_name,
                    config.model,
                    materials[0]["sha256"] if materials else None,
                    question_type_code,
                    lang,
                    effective_count,
                    status_value,
                    error,
                    requested_by,
                    now,
                    now if status_value == "failed" else None,
                    now if status_value == "failed" else None,
                    question_type_code,
                    age_group_id,
                    subject_id,
                    answer_mode or type_info.get("answer_mode") or "voice",
                    json_dumps({**(params or {}), "materialIds": [m["sha256"] for m in materials]}),
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
            job_params = job.get("params") or {}
            material_ids = job_params.get("materialIds") or ([job.get("materialId")] if job.get("materialId") else [])
            materials = [m for m in (get_image_material(self.settings, str(mid)) for mid in material_ids) if m]
            type_code = job.get("questionType") or "word_image"
            type_info = question_type(self.settings, type_code) or {}
            age_label = subject_label = ""
            with read_session(self.settings) as conn:
                if job.get("ageGroupId"):
                    row = conn.execute("SELECT name FROM age_groups WHERE id = ?", (job["ageGroupId"],)).fetchone()
                    age_label = row["name"] if row else ""
                if job.get("subjectId"):
                    row = conn.execute("SELECT name FROM subjects WHERE id = ?", (job["subjectId"],)).fetchone()
                    subject_label = row["name"] if row else ""
            if not materials:
                materials = [None]  # text/math types can be generated without an image
            created: list[dict[str, Any]] = []
            config = None
            for material in materials:
                image_bytes = read_material_bytes(self.settings, material) if material else None
                count_for_call = 1 if len(materials) > 1 else int(job["count"])
                if type_code == "word_image" and material:
                    items, call_config = generate_word_image_questions(
                        self.settings,
                        provider_name=job["provider"],
                        image_bytes=image_bytes or b"",
                        mime_type=material["content_type"],
                        lang=job["lang"],
                        count=count_for_call,
                    )
                else:
                    items, call_config = generate_choice_questions(
                        self.settings,
                        provider_name=job["provider"],
                        question_type=type_code,
                        lang=job["lang"],
                        count=count_for_call,
                        age_label=age_label,
                        subject_label=subject_label,
                        image_bytes=image_bytes,
                        mime_type=(material or {}).get("content_type", ""),
                        material_title=(material or {}).get("title", ""),
                    )
                config = call_config
                for item in items:
                    options = item.get("options") or []
                    question = create_question(
                        self.settings,
                        prompt=item["prompt"],
                        answer=item["answer"],
                        question_type=type_code,
                        lang=job["lang"],
                        image_id=(material or {}).get("sha256"),
                        options=options,
                        explanation=item.get("explanation", ""),
                        difficulty=item.get("difficulty", 1),
                        status_value="draft",
                        source="ai",
                        meta={
                            "generationJobId": job_id,
                            "provider": call_config.name,
                            "model": call_config.model,
                        },
                        age_group_id=job.get("ageGroupId"),
                        subject_id=job.get("subjectId"),
                        answer_mode=type_info.get("answer_mode") or job.get("answerMode") or "voice",
                        changed_by=f"ai:{call_config.name}",
                        change_note=f"generated by {call_config.name}/{call_config.model}",
                    )
                    created.append(question_admin_dict(self.settings, question))
            result = {
                "questionIds": [question["id"] for question in created],
                "questions": created,
                "provider": config.name if config else "",
                "model": config.model if config else "",
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
        "questionType": row["question_type"],
        "ageGroupId": row["age_group_id"],
        "subjectId": row["subject_id"],
        "answerMode": row["answer_mode"],
        "params": safe_json_loads(row["params_json"], {}),
        "requestedBy": row["requested_by"],
        "createdAt": row["created_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
    }
