"""Question CRUD, revisions, activation rules and answer judging."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from typing import Any

from .config import Settings
from .db import read_session, session
from .materials import admin_material_dict, get_image_material, material_public_dict
from .providers import judge_answer_ai
from .util import (
    iso,
    json_dumps,
    match_answer,
    match_answer_full,
    normalize_answer,
    safe_json_loads,
    split_accepted_answers,
    utcnow,
)

QUESTION_TYPES = {"word_image", "math", "text"}
STATUSES = ("draft", "reviewed", "active", "disabled")
LANGS = ("zh", "en")
QUESTION_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class QuestionError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return iso(utcnow())


def _validate_type(question_type: str) -> str:
    question_type = (question_type or "").strip().lower()
    if not QUESTION_TYPE_RE.match(question_type):
        raise QuestionError("invalid question type")
    return question_type


def _validate_lang(lang: str) -> str:
    lang = (lang or "zh").strip().lower()
    if lang not in LANGS:
        raise QuestionError("lang must be 'zh' or 'en'")
    return lang


def _validate_status(status_value: str) -> str:
    status_value = (status_value or "draft").strip().lower()
    if status_value not in STATUSES:
        raise QuestionError(f"status must be one of: {', '.join(STATUSES)}")
    return status_value


def _validate_difficulty(value: Any) -> int:
    try:
        difficulty = int(value)
    except (TypeError, ValueError):
        raise QuestionError("difficulty must be an integer from 1 to 5") from None
    if difficulty < 1 or difficulty > 5:
        raise QuestionError("difficulty must be between 1 and 5")
    return difficulty


def _normalise_image_id(settings: Settings, image_id: str | None) -> str | None:
    if image_id in (None, ""):
        return None
    material = get_image_material(settings, str(image_id))
    if not material:
        raise QuestionError(f"image not found: {image_id}", status_code=404)
    if material["kind"] != "image":
        raise QuestionError("material is not an image", status_code=422)
    return material["sha256"]


def _parse_options(options: Any) -> list[Any]:
    if options in (None, ""):
        return []
    if isinstance(options, list):
        return options
    if isinstance(options, str):
        parsed = safe_json_loads(options, None)
        if isinstance(parsed, list):
            return parsed
    raise QuestionError("options must be a JSON array")


def validate_for_activation(settings: Settings, question: dict[str, Any]) -> None:
    prompt = (question.get("prompt") or "").strip()
    answer = (question.get("answer") or "").strip()
    if not prompt:
        raise QuestionError("cannot activate a question without a prompt")
    if not answer:
        raise QuestionError("cannot activate a question without an answer")
    if not split_accepted_answers(answer):
        raise QuestionError("answer is empty after normalisation")
    if question.get("type") == "word_image":
        image_id = question.get("image_id")
        if not image_id:
            raise QuestionError(
                "cannot activate a word_image question without an image; "
                "upload an image and attach it first"
            )
        if not get_image_material(settings, str(image_id)):
            raise QuestionError("attached image no longer exists")


def _insert_revision(
    conn: sqlite3.Connection,
    question: dict[str, Any],
    *,
    changed_by: str,
    change_note: str,
) -> None:
    conn.execute(
        """
        INSERT INTO question_revisions(
            question_id, revision, type, lang, prompt, answer, image_id,
            options_json, explanation, difficulty, status, source,
            changed_by, change_note, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question["id"],
            question["revision"],
            question["type"],
            question["lang"],
            question["prompt"],
            question["answer"],
            question.get("image_id"),
            question["options_json"],
            question["explanation"],
            question["difficulty"],
            question["status"],
            question["source"],
            changed_by,
            change_note,
            _now(),
        ),
    )


def create_question(
    settings: Settings,
    *,
    prompt: str,
    answer: str,
    question_type: str = "word_image",
    lang: str = "zh",
    image_id: str | None = None,
    options: Any = None,
    explanation: str = "",
    difficulty: int = 1,
    status_value: str = "draft",
    source: str = "manual",
    meta: dict[str, Any] | None = None,
    changed_by: str = "admin",
    change_note: str = "created",
) -> dict[str, Any]:
    question_type = _validate_type(question_type)
    lang = _validate_lang(lang)
    status_value = _validate_status(status_value)
    difficulty = _validate_difficulty(difficulty)
    prompt = (prompt or "").strip()
    answer = (answer or "").strip()
    if not prompt:
        raise QuestionError("prompt is required")
    if not answer:
        raise QuestionError("answer is required")
    normalized_image = _normalise_image_id(settings, image_id)
    options_list = _parse_options(options)
    if len(prompt) > 500:
        raise QuestionError("prompt is too long (max 500 characters)")
    if len(answer) > 500:
        raise QuestionError("answer is too long (max 500 characters)")

    record = {
        "type": question_type,
        "lang": lang,
        "prompt": prompt,
        "answer": answer,
        "image_id": normalized_image,
        "options_json": json_dumps(options_list),
        "explanation": (explanation or "").strip()[:1000],
        "difficulty": difficulty,
        "status": status_value,
        "source": source if source in {"manual", "ai"} else "manual",
        "meta_json": json_dumps(meta or {}),
        "revision": 1,
    }
    if status_value == "active":
        validate_for_activation(settings, record)

    now = _now()
    with session(settings) as conn:
        cursor = conn.execute(
            """
            INSERT INTO questions(type, lang, prompt, answer, image_id,
                                  options_json, explanation, difficulty,
                                  status, revision, source, meta_json,
                                  created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                record["type"],
                record["lang"],
                record["prompt"],
                record["answer"],
                record["image_id"],
                record["options_json"],
                record["explanation"],
                record["difficulty"],
                record["status"],
                record["source"],
                record["meta_json"],
                now,
                now,
            ),
        )
        question = dict(
            conn.execute("SELECT * FROM questions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        )
        _insert_revision(
            conn, question, changed_by=changed_by, change_note=change_note or "created"
        )
    return question


def update_question(
    settings: Settings,
    question_id: int,
    *,
    fields: dict[str, Any],
    changed_by: str = "admin",
    change_note: str = "",
) -> dict[str, Any]:
    question = get_question(settings, question_id)
    if not question:
        raise QuestionError("question not found", status_code=404)

    merged = dict(question)
    if "prompt" in fields:
        prompt = (fields["prompt"] or "").strip()
        if not prompt:
            raise QuestionError("prompt cannot be empty")
        if len(prompt) > 500:
            raise QuestionError("prompt is too long (max 500 characters)")
        merged["prompt"] = prompt
    if "answer" in fields:
        answer = (fields["answer"] or "").strip()
        if not answer:
            raise QuestionError("answer cannot be empty")
        if len(answer) > 500:
            raise QuestionError("answer is too long (max 500 characters)")
        merged["answer"] = answer
    if "imageId" in fields:
        merged["image_id"] = _normalise_image_id(settings, fields["imageId"])
    if "lang" in fields:
        merged["lang"] = _validate_lang(fields["lang"])
    if "type" in fields:
        merged["type"] = _validate_type(fields["type"])
    if "options" in fields:
        merged["options_json"] = json_dumps(_parse_options(fields["options"]))
    if "explanation" in fields:
        merged["explanation"] = (fields["explanation"] or "").strip()[:1000]
    if "difficulty" in fields:
        merged["difficulty"] = _validate_difficulty(fields["difficulty"])
    if "status" in fields:
        merged["status"] = _validate_status(fields["status"])
    if "meta" in fields and isinstance(fields["meta"], dict):
        merged["meta_json"] = json_dumps(fields["meta"])

    if merged["status"] == "active":
        validate_for_activation(settings, merged)

    merged["revision"] = int(question["revision"]) + 1
    merged["changed_at"] = _now()
    with session(settings) as conn:
        conn.execute(
            """
            UPDATE questions SET type = ?, lang = ?, prompt = ?, answer = ?,
                image_id = ?, options_json = ?, explanation = ?,
                difficulty = ?, status = ?, revision = ?, meta_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                merged["type"],
                merged["lang"],
                merged["prompt"],
                merged["answer"],
                merged["image_id"],
                merged["options_json"],
                merged["explanation"],
                merged["difficulty"],
                merged["status"],
                merged["revision"],
                merged["meta_json"],
                merged["changed_at"],
                question_id,
            ),
        )
        updated = dict(
            conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        )
        _insert_revision(
            conn,
            updated,
            changed_by=changed_by,
            change_note=change_note or f"revision {updated['revision']}",
        )
    return updated


def set_status(
    settings: Settings,
    question_id: int,
    status_value: str,
    *,
    changed_by: str = "admin",
    change_note: str = "",
) -> dict[str, Any]:
    status_value = _validate_status(status_value)
    return update_question(
        settings,
        question_id,
        fields={"status": status_value},
        changed_by=changed_by,
        change_note=change_note or f"status -> {status_value}",
    )


def get_question(settings: Settings, question_id: int) -> dict[str, Any] | None:
    with read_session(settings) as conn:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        return dict(row) if row else None


def get_questions_by_ids(settings: Settings, question_ids: Iterable[int]) -> list[dict[str, Any]]:
    ids = [int(qid) for qid in question_ids]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with read_session(settings) as conn:
        rows = conn.execute(f"SELECT * FROM questions WHERE id IN ({placeholders})", ids).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    return [by_id[qid] for qid in ids if qid in by_id]


def list_questions(
    settings: Settings,
    *,
    status_value: str | None = None,
    question_type: str | None = None,
    lang: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []
    if status_value:
        where.append("status = ?")
        params.append(status_value)
    if question_type:
        where.append("type = ?")
        params.append(question_type)
    if lang:
        where.append("lang = ?")
        params.append(lang)
    if search:
        where.append("(prompt LIKE ? OR answer LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with read_session(settings) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM questions {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM questions {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [dict(row) for row in rows], total


def list_revisions(settings: Settings, question_id: int, limit: int = 100) -> list[dict[str, Any]]:
    with read_session(settings) as conn:
        rows = conn.execute(
            """
            SELECT * FROM question_revisions WHERE question_id = ?
            ORDER BY revision DESC LIMIT ?
            """,
            (question_id, max(1, min(limit, 500))),
        ).fetchall()
        return [dict(row) for row in rows]


def list_recent_revisions(settings: Settings, limit: int = 50) -> list[dict[str, Any]]:
    with read_session(settings) as conn:
        rows = conn.execute(
            """
            SELECT r.*, q.prompt AS question_prompt
            FROM question_revisions r
            JOIN questions q ON q.id = r.question_id
            ORDER BY r.id DESC LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [dict(row) for row in rows]


def count_active(settings: Settings) -> int:
    with read_session(settings) as conn:
        return conn.execute("SELECT COUNT(*) FROM questions WHERE status = 'active'").fetchone()[0]


def select_active_questions(settings: Settings, count: int) -> list[dict[str, Any]]:
    """Randomly pick ``count`` active questions without repetition."""
    with read_session(settings) as conn:
        rows = conn.execute(
            """
            SELECT * FROM questions
            WHERE status = 'active'
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (count,),
        ).fetchall()
        return [dict(row) for row in rows]


def _image_url(settings: Settings, question: dict[str, Any], session_id: str | None) -> str | None:
    image_id = question.get("image_id")
    if not image_id:
        return None
    suffix = f"?s={session_id}" if session_id else ""
    return f"{settings.image_url_prefix}/{image_id}{suffix}"


def question_public_dict(
    settings: Settings, question: dict[str, Any], session_id: str | None = None
) -> dict[str, Any]:
    """Question payload sent to the TV.

    ``say`` is the target pronunciation for repeat-after-me TTS; it is not
    rendered as text in the TV UI.
    """
    answer = str(question.get("answer") or "").split("|")[0].strip()
    return {
        "id": question["id"],
        "type": question["type"],
        "prompt": question["prompt"],
        "imageUrl": _image_url(settings, question, session_id),
        # Repeat-after-me needs the TV to speak the target once; never render this as text.
        "say": answer or None,
        "lang": question["lang"],
        "difficulty": question["difficulty"],
    }


def question_admin_dict(settings: Settings, question: dict[str, Any]) -> dict[str, Any]:
    image = (
        get_image_material(settings, str(question["image_id"]))
        if question.get("image_id")
        else None
    )
    return {
        "id": question["id"],
        "type": question["type"],
        "lang": question["lang"],
        "prompt": question["prompt"],
        "answer": question["answer"],
        "imageId": question.get("image_id"),
        "image": admin_material_dict(settings, image) if image else None,
        "options": safe_json_loads(question.get("options_json"), []),
        "explanation": question["explanation"],
        "difficulty": question["difficulty"],
        "status": question["status"],
        "revision": question["revision"],
        "source": question["source"],
        "meta": safe_json_loads(question.get("meta_json"), {}),
        "createdAt": question["created_at"],
        "updatedAt": question["updated_at"],
    }


def revision_admin_dict(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": revision["id"],
        "questionId": revision["question_id"],
        "revision": revision["revision"],
        "type": revision["type"],
        "lang": revision["lang"],
        "prompt": revision["prompt"],
        "answer": revision["answer"],
        "imageId": revision.get("image_id"),
        "options": safe_json_loads(revision.get("options_json"), []),
        "explanation": revision["explanation"],
        "difficulty": revision["difficulty"],
        "status": revision["status"],
        "source": revision["source"],
        "changedBy": revision["changed_by"],
        "changeNote": revision["change_note"],
        "createdAt": revision["created_at"],
    }


def judge_transcript(
    settings: Settings,
    question: dict[str, Any],
    transcript: str,
    *,
    allow_ai: bool = True,
) -> tuple[bool, str, dict[str, Any]]:
    """Grade a transcript.

    Exact matching accepts alternatives separated by ``|``.  When enabled and
    the exact match fails, an optional AI text judge can be consulted.
    """
    normalized = normalize_answer(transcript)
    accepted = split_accepted_answers(question.get("answer", ""))
    matched, retry, method, detail = match_answer_full(accepted, transcript)
    if matched:
        detail["score"] = {"exact": 100, "pinyin": 94, "phonetic": 90, "fuzzy": 86}.get(method, 85)
        return True, method, detail
    if retry:
        detail["retry"] = True
        detail["score"] = 60
        return False, "near_miss", detail
    detail["transcriptNormalized"] = normalized
    detail["acceptedCount"] = len(accepted)
    if allow_ai:
        ai_result = judge_answer_ai(
            settings,
            question_prompt=question.get("prompt", ""),
            reference_answer=question.get("answer", ""),
            transcript=transcript,
        )
        if ai_result is not None:
            detail["aiJudge"] = ai_result
            detail["score"] = 85 if ai_result else 0
            return bool(ai_result), "ai", detail
    detail["score"] = 0
    return False, "exact", detail
