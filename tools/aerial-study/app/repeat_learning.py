"""Independent repeat-learning: three cards, audio-only scoring, no ASR/text gate."""
from __future__ import annotations

import json
import random
from datetime import timedelta
from typing import Any

from .audio_judge import judge_repeat_audio
from .config import Settings
from .db import read_session, session
from .questions import get_question, question_public_dict, select_active_questions
from .util import iso, json_dumps, new_id, parse_iso, safe_json_loads, utcnow

CARD_COUNT = 3
MAX_NO_SPEECH = 2


class RepeatLearningError(Exception):
    def __init__(self, message: str, status_code: int = 409, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def _now() -> str:
    return iso(utcnow())


def _card(settings: Settings, question: dict[str, Any]) -> dict[str, Any]:
    answer = str(question.get("answer") or "").split("|")[0].strip()
    word = answer or str(question.get("prompt") or "").strip()
    letters = [ch.upper() for ch in word if ch.isalpha()]
    public = question_public_dict(settings, question)
    return {
        "id": question["id"],
        "imageUrl": public.get("imageUrl"),
        "word": word,
        "letters": letters,
        "spellingText": f"{word}, " + ". ".join(letters) if letters else word,
    }


def _row(settings: Settings, session_id: str) -> dict[str, Any] | None:
    with read_session(settings) as conn:
        row = conn.execute("SELECT * FROM repeat_sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def _cards(settings: Settings, row: dict[str, Any]) -> list[dict[str, Any]]:
    ids = [int(value) for value in safe_json_loads(row.get("card_ids_json"), [])]
    return [_card(settings, get_question(settings, cid)) for cid in ids if get_question(settings, cid)]


def session_view(settings: Settings, row: dict[str, Any]) -> dict[str, Any]:
    cards = _cards(settings, row)
    current = int(row.get("current_index") or 0)
    return {
        "session": {
            "id": row["id"],
            "status": row["status"],
            "total": len(cards),
            "currentIndex": current,
            "totalScore": int(row.get("total_score") or 0),
            "createdAt": row["created_at"],
            "finishedAt": row.get("finished_at"),
        },
        "cards": cards,
        "progress": {
            "answered": current,
            "total": len(cards),
            "finished": row["status"] == "finished",
        },
    }


def start_session(
    settings: Settings,
    *,
    device_id: str = "",
    age_group_id: int | None = None,
    subject_id: int | None = None,
) -> dict[str, Any]:
    selected = select_active_questions(
        settings,
        CARD_COUNT,
        age_group_id=age_group_id,
        subject_id=subject_id,
        question_type_code="word_image",
    )
    if len(selected) < CARD_COUNT:
        raise RepeatLearningError(
            f"not enough active word image cards: need {CARD_COUNT}, have {len(selected)}",
            status_code=409,
        )
    random.shuffle(selected)
    card_ids = [int(question["id"]) for question in selected]
    session_id = new_id()
    now = utcnow()
    row = {
        "id": session_id,
        "device_id": device_id[:128],
        "status": "active",
        "card_ids_json": json_dumps(card_ids),
        "current_index": 0,
        "scores_json": "[]",
        "total_score": 0,
        "created_at": iso(now),
        "updated_at": iso(now),
        "finished_at": None,
    }
    with session(settings) as conn:
        conn.execute(
            """
            INSERT INTO repeat_sessions(
                id, device_id, status, card_ids_json, current_index,
                scores_json, total_score, created_at, updated_at, finished_at)
            VALUES(?,?,?,?,0,'[]',0,?,?,NULL)
            """,
            (session_id, row["device_id"], "active", row["card_ids_json"], row["created_at"], row["updated_at"]),
        )
    created = _row(settings, session_id)
    assert created is not None
    return session_view(settings, created)


def _check_session(row: dict[str, Any]) -> None:
    if row["status"] == "finished":
        raise RepeatLearningError("session already finished", status_code=409)
    try:
        if parse_iso(row["created_at"]) + timedelta(hours=24) <= utcnow():
            raise RepeatLearningError("session expired", status_code=410)
    except (KeyError, ValueError):
        raise RepeatLearningError("session expired", status_code=410) from None


def submit_attempt(
    settings: Settings,
    session_id: str,
    *,
    card_id: int,
    audio: bytes | None,
) -> dict[str, Any]:
    row = _row(settings, session_id)
    if not row:
        raise RepeatLearningError("session not found", status_code=404)
    _check_session(row)
    card_ids = [int(value) for value in safe_json_loads(row["card_ids_json"], [])]
    current = int(row.get("current_index") or 0)
    if current >= len(card_ids):
        raise RepeatLearningError("session already finished", status_code=409)
    expected = card_ids[current]
    if int(card_id) != expected:
        raise RepeatLearningError(f"wrong card: expected {expected}", status_code=409)
    question = get_question(settings, expected)
    if not question:
        raise RepeatLearningError("card no longer exists", status_code=410)
    card = _card(settings, question)
    previous = safe_json_loads(row.get("scores_json"), [])
    scores = [int(value) for value in previous] if isinstance(previous, list) else []
    with read_session(settings) as conn:
        no_speech_count = conn.execute(
            "SELECT COUNT(*) FROM repeat_attempts WHERE session_id=? AND card_id=? AND verdict='no_speech'",
            (session_id, expected),
        ).fetchone()[0]
        attempt_no = conn.execute(
            "SELECT COUNT(*) FROM repeat_attempts WHERE session_id=?", (session_id,)
        ).fetchone()[0] + 1
    result = judge_repeat_audio(
        settings,
        word=card["word"],
        letters=card["letters"],
        audio=audio,
    )
    if result is None:
        raise RepeatLearningError("语音评分暂时不可用，请重试", status_code=503, retryable=True)
    verdict = str(result.get("verdict") or "near")
    score = max(0, min(100, int(result.get("score") or 0)))
    now = _now()
    if verdict == "no_speech":
        if no_speech_count + 1 >= MAX_NO_SPEECH:
            scores.append(0)
            next_index = current + 1
            finished = next_index >= len(card_ids)
            with session(settings) as conn:
                conn.execute(
                    """INSERT INTO repeat_attempts(session_id,card_id,attempt_no,score,verdict,heard,feedback,
                       pronunciation_json,provider,model,created_at) VALUES(?,?,?,0,'no_speech',?,?,?,?,?,?)""",
                    (session_id, expected, attempt_no, result.get("heard", ""), result.get("feedback", ""),
                     json_dumps(result.get("pronunciation") or {}), result.get("provider", ""), result.get("model", ""), now),
                )
                conn.execute(
                    "UPDATE repeat_sessions SET current_index=?, scores_json=?, total_score=?, status=?, updated_at=?, finished_at=? WHERE id=?",
                    (next_index, json_dumps(scores), sum(scores), "finished" if finished else "active", now, now if finished else None, session_id),
                )
            updated = _row(settings, session_id)
            assert updated
            return _result(settings, updated, score=0, verdict="no_speech", heard=result.get("heard", ""), feedback="没有听到清晰的声音", finished=finished)
        with session(settings) as conn:
            conn.execute(
                """INSERT INTO repeat_attempts(session_id,card_id,attempt_no,score,verdict,heard,feedback,
                   pronunciation_json,provider,model,created_at) VALUES(?,?,?,0,'no_speech',?,?,?,?,?,?)""",
                (session_id, expected, attempt_no, result.get("heard", ""), result.get("feedback", ""),
                 json_dumps(result.get("pronunciation") or {}), result.get("provider", ""), result.get("model", ""), now),
            )
        return _result(settings, _row(settings, session_id) or row, score=0, verdict="no_speech", heard=result.get("heard", ""), feedback="没有听清，请再读一次", retry=True, finished=False)

    scores.append(score)
    next_index = current + 1
    finished = next_index >= len(card_ids)
    with session(settings) as conn:
        conn.execute(
            """INSERT INTO repeat_attempts(session_id,card_id,attempt_no,score,verdict,heard,feedback,
               pronunciation_json,provider,model,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, expected, attempt_no, score, verdict, result.get("heard", ""), result.get("feedback", ""),
             json_dumps(result.get("pronunciation") or {}), result.get("provider", ""), result.get("model", ""), now),
        )
        conn.execute(
            "UPDATE repeat_sessions SET current_index=?, scores_json=?, total_score=?, status=?, updated_at=?, finished_at=? WHERE id=?",
            (next_index, json_dumps(scores), sum(scores), "finished" if finished else "active", now, now if finished else None, session_id),
        )
    updated = _row(settings, session_id)
    assert updated
    return _result(settings, updated, score=score, verdict=verdict, heard=result.get("heard", ""), feedback=result.get("feedback", ""), finished=finished)


def _result(settings: Settings, row: dict[str, Any], *, score: int, verdict: str, heard: str, feedback: str, finished: bool, retry: bool = False) -> dict[str, Any]:
    cards = _cards(settings, row)
    current = int(row.get("current_index") or 0)
    next_card = cards[current] if current < len(cards) else None
    return {
        "score": score,
        "verdict": verdict,
        "heard": heard,
        "feedback": feedback,
        "retry": retry,
        "finished": finished,
        "totalScore": int(row.get("total_score") or 0),
        "progress": {"answered": current, "total": len(cards), "finished": finished},
        "nextCard": next_card,
    }


def list_sessions(settings: Settings, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    with read_session(settings) as conn:
        total = conn.execute("SELECT COUNT(*) FROM repeat_sessions").fetchone()[0]
        rows = conn.execute("SELECT * FROM repeat_sessions ORDER BY created_at DESC LIMIT ? OFFSET ?", (max(1, min(limit, 200)), max(0, offset))).fetchall()
        items = []
        for raw in rows:
            row = dict(raw)
            items.append({
                "id": row["id"], "status": row["status"], "deviceId": row.get("device_id", ""),
                "totalScore": int(row.get("total_score") or 0),
                "currentIndex": int(row.get("current_index") or 0),
                "createdAt": row["created_at"], "finishedAt": row.get("finished_at"),
            })
    return items, total


def session_detail(settings: Settings, session_id: str) -> dict[str, Any] | None:
    row = _row(settings, session_id)
    if not row:
        return None
    with read_session(settings) as conn:
        attempts = [dict(item) for item in conn.execute("SELECT * FROM repeat_attempts WHERE session_id=? ORDER BY id", (session_id,)).fetchall()]
    return {"session": session_view(settings, row)["session"], "cards": _cards(settings, row), "attempts": attempts}
