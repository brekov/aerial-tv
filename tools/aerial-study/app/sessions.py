"""Quiz sessions: question selection, progress and wrong-answer restart logic."""

from __future__ import annotations

from typing import Any

from .config import Settings
from .db import read_session, session
from .questions import (
    count_active,
    get_question,
    get_questions_by_ids,
    question_public_dict,
    select_active_questions,
)
from .util import iso, parse_iso, safe_json_loads, utcnow


class SessionError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return iso(utcnow())


def get_session_row(settings: Settings, session_id: str) -> dict[str, Any] | None:
    with read_session(settings) as conn:
        row = conn.execute("SELECT * FROM quiz_sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def is_expired(row: dict[str, Any]) -> bool:
    try:
        return parse_iso(row["expires_at"]) <= utcnow()
    except (KeyError, ValueError):
        return True


def effective_status(row: dict[str, Any]) -> str:
    if is_expired(row) and row.get("status") != "finished":
        return "expired"
    return row.get("status", "active")


def progress(row: dict[str, Any]) -> dict[str, Any]:
    total = len(safe_json_loads(row.get("question_ids_json"), []))
    current = int(row.get("current_index") or 0)
    return {
        "currentIndex": current,
        "answered": current,
        "total": total,
        "remaining": max(0, total - current),
        "correct": int(row.get("correct_count") or 0),
        "wrong": int(row.get("wrong_count") or 0),
        "restarts": int(row.get("restarts") or 0),
        "finished": row.get("status") == "finished",
    }


def _session_header(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": effective_status(row),
        "deviceId": row.get("device_id", ""),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "expiresAt": row["expires_at"],
        "finishedAt": row.get("finished_at"),
    }


def session_view(
    settings: Settings, row: dict[str, Any], *, include_questions: bool = True
) -> dict[str, Any]:
    question_ids = safe_json_loads(row.get("question_ids_json"), [])
    questions = get_questions_by_ids(settings, question_ids)
    payload: dict[str, Any] = {
        "session": _session_header(row),
        "progress": progress(row),
        "finished": row["status"] == "finished",
    }
    if include_questions:
        payload["questions"] = [
            question_public_dict(settings, question, row["id"]) for question in questions
        ]
    return payload


def _next_question_payload(
    settings: Settings, row: dict[str, Any], question: dict[str, Any] | None
) -> dict[str, Any] | None:
    if question is None:
        return None
    return question_public_dict(settings, question, row["id"])


def list_sessions(
    settings: Settings, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with read_session(settings) as conn:
        total = conn.execute("SELECT COUNT(*) FROM quiz_sessions").fetchone()[0]
        rows = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM quiz_attempts a WHERE a.session_id = s.id)
                       AS attempt_count
            FROM quiz_sessions s
            ORDER BY s.created_at DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    items = []
    for raw_row in rows:
        row = dict(raw_row)
        item = _session_header(row)
        item["progress"] = progress(row)
        item["attemptCount"] = row["attempt_count"]
        items.append(item)
    return items, total


def session_detail(settings: Settings, session_id: str) -> dict[str, Any] | None:
    row = get_session_row(settings, session_id)
    if not row:
        return None
    with read_session(settings) as conn:
        attempts = conn.execute(
            """
            SELECT a.*, q.prompt AS question_prompt, q.answer AS question_answer
            FROM quiz_attempts a
            LEFT JOIN questions q ON q.id = a.question_id
            WHERE a.session_id = ?
            ORDER BY a.attempt_no ASC
            """,
            (session_id,),
        ).fetchall()
    detail = session_view(settings, row)
    detail["attempts"] = [
        {
            "attemptNo": attempt["attempt_no"],
            "questionId": attempt["question_id"],
            "questionPrompt": attempt["question_prompt"],
            "questionAnswer": attempt["question_answer"],
            "transcript": attempt["transcript"],
            "correct": bool(attempt["correct"]),
            "judgeMethod": attempt["judge_method"],
            "createdAt": attempt["created_at"],
        }
        for attempt in attempts
    ]
    return detail


def count_sessions(settings: Settings) -> int:
    with read_session(settings) as conn:
        return conn.execute("SELECT COUNT(*) FROM quiz_sessions").fetchone()[0]


def wrong_questions(
    settings: Settings,
    *,
    age_group_id: int | None = None,
    subject_id: int | None = None,
    question_type_code: str | None = None,
    min_wrong: int = 1,
    limit: int = 100,
) -> list[dict[str, Any]]:
    where = ["q.deleted_at IS NULL"]
    args: list[Any] = []
    for column, value in (("q.age_group_id", age_group_id), ("q.subject_id", subject_id), ("q.type", question_type_code)):
        if value is not None:
            where.append(f"{column} = ?")
            args.append(value)
    args.extend([max(1, int(min_wrong)), max(1, min(int(limit), 500))])
    with read_session(settings) as conn:
        rows = conn.execute(
            f"""
            SELECT q.id AS question_id, q.prompt, q.answer, q.type, q.answer_mode,
                   q.age_group_id, q.subject_id, q.difficulty, q.image_id,
                   COUNT(a.id) AS total_attempts,
                   SUM(CASE WHEN a.correct = 0 THEN 1 ELSE 0 END) AS wrong_attempts,
                   MAX(CASE WHEN a.correct = 0 THEN a.created_at ELSE NULL END) AS last_wrong_at
            FROM quiz_attempts a
            JOIN questions q ON q.id = a.question_id
            WHERE {' AND '.join(where)}
            GROUP BY q.id
            HAVING wrong_attempts >= ?
            ORDER BY wrong_attempts DESC, last_wrong_at DESC
            LIMIT ?
            """,
            [*args[:-2], args[-2], args[-1]],
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        total = int(item["total_attempts"] or 0)
        wrong = int(item["wrong_attempts"] or 0)
        item["wrongRate"] = round(wrong / total, 3) if total else 0.0
        result.append(item)
    return result


def question_attempts(settings: Settings, question_id: int, limit: int = 100) -> list[dict[str, Any]]:
    with read_session(settings) as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_attempts WHERE question_id = ? ORDER BY id DESC LIMIT ?",
            (question_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(row) for row in rows]
