"""Quiz sessions: question selection, progress and wrong-answer restart logic."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .audio_judge import judge_audio
from .config import Settings
from .db import read_session, session
from .questions import (
    count_active,
    get_question,
    get_questions_by_ids,
    judge_transcript,
    question_public_dict,
    select_active_questions,
)
from .util import iso, json_dumps, new_id, normalize_answer, parse_iso, safe_json_loads, split_accepted_answers, utcnow


class SessionError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return iso(utcnow())


def create_session(
    settings: Settings,
    *,
    device_id: str = "",
    age_group_id: int | None = None,
    subject_id: int | None = None,
    answer_mode: str | None = None,
    question_type_code: str | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    needed = max(1, min(int(count or settings.questions_per_session), settings.questions_per_session))
    selected = select_active_questions(
        settings,
        needed,
        age_group_id=age_group_id,
        subject_id=subject_id,
        answer_mode=answer_mode,
        question_type_code=question_type_code,
    )
    if len(selected) < needed:
        raise SessionError(
            f"not enough matching active questions: need {needed}, have {len(selected)}; "
            "activate questions in the admin page first",
            status_code=409,
        )
    question_ids = [question["id"] for question in selected]
    session_id = new_id()
    now = utcnow()
    created_at = iso(now)
    expires_at = iso(now + timedelta(hours=settings.session_ttl_hours))
    with session(settings) as conn:
        conn.execute(
            """
            INSERT INTO quiz_sessions(
                id, device_id, status, question_ids_json, current_index,
                correct_count, wrong_count, restarts, created_at, updated_at,
                expires_at)
            VALUES(?, ?, 'active', ?, 0, 0, 0, 0, ?, ?, ?)
            """,
            (
                session_id,
                device_id[:128],
                json_dumps(question_ids),
                created_at,
                created_at,
                expires_at,
            ),
        )
    row = get_session_row(settings, session_id)
    assert row is not None
    return {
        "session": _session_header(row),
        "questions": [
            question_public_dict(settings, question, session_id) for question in selected
        ],
        "expiresAt": row["expires_at"],
    }


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


def load_session(settings: Settings, session_id: str) -> dict[str, Any]:
    row = get_session_row(settings, session_id)
    if not row:
        raise SessionError("session not found", status_code=404)
    if is_expired(row) and row["status"] != "finished":
        raise SessionError("session expired", status_code=410)
    return row


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


def submit_answer(
    settings: Settings,
    session_id: str,
    *,
    question_id: int,
    transcript: str,
    audio: bytes | None = None,
    selected_option: int | None = None,
    allow_ai_judge: bool = True,
) -> dict[str, Any]:
    row = load_session(settings, session_id)
    if row["status"] == "finished":
        raise SessionError("session already finished", status_code=409)
    question_ids = [int(value) for value in safe_json_loads(row["question_ids_json"], [])]
    current_index = int(row.get("current_index") or 0)
    if current_index >= len(question_ids):
        raise SessionError("session already finished", status_code=409)
    expected_question_id = question_ids[current_index]
    if int(question_id) != expected_question_id:
        raise SessionError(
            f"wrong question: expected question {expected_question_id} at index {current_index}",
            status_code=409,
        )
    question = get_question(settings, expected_question_id)
    if not question:
        raise SessionError("question no longer exists", status_code=410)

    if question.get("answer_mode") == "choice":
        options = safe_json_loads(question.get("options_json"), [])
        if selected_option is None or not isinstance(selected_option, int) or not 0 <= selected_option < len(options):
            raise SessionError("a valid selectedOption is required for this question", status_code=422)
        accepted = split_accepted_answers(str(question.get("answer") or ""))
        correct = normalize_answer(str(options[selected_option])) in {normalize_answer(item) for item in accepted}
        judge_method = "choice"
        judge_detail = {"selectedOption": selected_option, "selectedText": options[selected_option], "score": 100 if correct else 0}
    else:
        correct, judge_method, judge_detail = judge_transcript(
            settings,
            question,
            transcript,
            allow_ai=allow_ai_judge,
        )
    score = int(judge_detail.get("score") or 0)

    audio_result: dict[str, Any] | None = None
    audio_retry = False
    if audio:
        accepted = question.get("answer", "")
        word = accepted.split("|", 1)[0].strip() if accepted else ""
        audio_result = judge_audio(settings, reference=accepted, word=word, audio=audio)
        if audio_result:
            judge_detail["audioJudge"] = audio_result
            pronunciation = audio_result.get("pronunciation") or {}
            overall = pronunciation.get("overall")
            # High-confidence audio veto for gross mispronunciations.  The
            # normal "near" case remains coaching only until thresholds are
            # calibrated on real children.
            if (
                correct
                and isinstance(overall, int)
                and overall < 50
                and audio_result.get("verdict") == "wrong"
                and float(audio_result.get("confidence") or 0.0) >= 0.85
            ):
                correct = False
                audio_retry = True
                judge_method = "near_miss"
                judge_detail["retry"] = True
                judge_detail["audioTriggeredRetry"] = True
                score = overall

    now = utcnow()
    timestamp = iso(now)
    finished = False
    retry = bool(judge_detail.get("retry")) or audio_retry
    with session(settings) as conn:
        attempt_no = (
            conn.execute(
                "SELECT COUNT(*) FROM quiz_attempts WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            + 1
        )
        if retry:
            prior_retries = conn.execute(
                "SELECT COUNT(*) FROM quiz_attempts WHERE session_id = ? AND question_id = ? AND judge_method = 'near_miss'",
                (session_id, expected_question_id),
            ).fetchone()[0]
            if prior_retries >= 1:
                # Only one follow-along retry per question; the second near miss is a wrong answer.
                retry = False
                judge_detail = {**judge_detail, "retryLimitReached": True}
        conn.execute(
            """
            INSERT INTO quiz_attempts(
                session_id, question_id, attempt_no, transcript, correct,
                judge_method, judge_detail_json, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                expected_question_id,
                attempt_no,
                (transcript or "")[:2000],
                1 if correct else 0,
                judge_method,
                json_dumps(judge_detail),
                timestamp,
            ),
        )
        if retry:
            # Near miss: keep the same question and the same five-question progress.
            pass
        elif correct:
            next_index = current_index + 1
            finished = next_index >= len(question_ids)
            conn.execute(
                """
                UPDATE quiz_sessions
                SET current_index = ?, correct_count = correct_count + 1,
                    status = ?, updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    next_index,
                    "finished" if finished else "active",
                    timestamp,
                    timestamp if finished else None,
                    session_id,
                ),
            )
        else:
            # A wrong answer restarts the same five-question run from the start.
            conn.execute(
                """
                UPDATE quiz_sessions
                SET current_index = 0, wrong_count = wrong_count + 1,
                    restarts = restarts + 1, status = 'active', updated_at = ?
                WHERE id = ?
                """,
                (timestamp, session_id),
            )
    row = get_session_row(settings, session_id)
    assert row is not None
    result: dict[str, Any] = {
        "correct": bool(correct),
        "score": max(0, min(100, score)),
        "retry": bool(retry),
        "progress": progress(row),
        # A retry keeps the current question; it is not a restart.
        "finished": bool(finished),
        "restart": not bool(correct) and not bool(retry),
        "questionId": expected_question_id,
        "judgeMethod": judge_method,
        "session": _session_header(row),
    }
    if audio_result:
        result["mimoJudge"] = {
            "verdict": audio_result.get("verdict"),
            "confidence": audio_result.get("confidence"),
            "heard": audio_result.get("heard"),
            "issues": audio_result.get("issues"),
            "feedback": audio_result.get("feedback"),
        }
        result["pronunciation"] = audio_result.get("pronunciation")
        result["decision"] = "pass" if correct else ("retry" if retry else "restart")
        result["audioShadow"] = True
    if correct and not finished:
        next_question = get_question(settings, question_ids[current_index + 1])
        result["nextQuestion"] = _next_question_payload(settings, row, next_question)
    return result


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
                   q.age_group_id, q.subject_id, q.difficulty,
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
