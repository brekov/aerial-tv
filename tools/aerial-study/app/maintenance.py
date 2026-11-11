"""Small, explicitly-confirmed maintenance actions."""
from __future__ import annotations

from typing import Any

from .config import Settings
from .db import read_session, session


def seed_candidates(settings: Settings) -> list[dict[str, Any]]:
    with read_session(settings) as conn:
        rows = conn.execute(
            """
            SELECT id, prompt, answer, status, image_id
            FROM questions
            WHERE prompt LIKE 'seed prompt %'
               OR (answer LIKE 'seed%' AND source = 'manual')
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def cleanup_seed(settings: Settings, *, dry_run: bool = True) -> dict[str, Any]:
    candidates = seed_candidates(settings)
    ids = [int(item["id"]) for item in candidates]
    result: dict[str, Any] = {
        "dryRun": dry_run,
        "candidates": candidates,
        "questionIds": ids,
        "deletedQuestions": 0,
        "deletedAttempts": 0,
        "deletedRevisions": 0,
    }
    if dry_run or not ids:
        return result
    placeholders = ",".join("?" for _ in ids)
    with session(settings) as conn:
        attempts = conn.execute(
            f"DELETE FROM quiz_attempts WHERE question_id IN ({placeholders})", ids
        ).rowcount
        revisions = conn.execute(
            f"DELETE FROM question_revisions WHERE question_id IN ({placeholders})", ids
        ).rowcount
        questions = conn.execute(
            f"DELETE FROM questions WHERE id IN ({placeholders})", ids
        ).rowcount
    result.update(
        deletedQuestions=questions,
        deletedAttempts=attempts,
        deletedRevisions=revisions,
    )
    return result


def non_active_candidates(settings: Settings) -> list[dict[str, Any]]:
    with read_session(settings) as conn:
        rows = conn.execute(
            """
            SELECT id, prompt, answer, status, image_id
            FROM questions
            WHERE status != 'active' AND deleted_at IS NULL
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def cleanup_non_active(settings: Settings, *, dry_run: bool = True) -> dict[str, Any]:
    candidates = non_active_candidates(settings)
    ids = [int(item["id"]) for item in candidates]
    result: dict[str, Any] = {
        "dryRun": dry_run,
        "candidates": candidates,
        "questionIds": ids,
        "deletedQuestions": 0,
        "deletedAttempts": 0,
        "deletedRevisions": 0,
    }
    if dry_run or not ids:
        return result
    placeholders = ",".join("?" for _ in ids)
    with session(settings) as conn:
        attempts = conn.execute(f"DELETE FROM quiz_attempts WHERE question_id IN ({placeholders})", ids).rowcount
        revisions = conn.execute(f"DELETE FROM question_revisions WHERE question_id IN ({placeholders})", ids).rowcount
        questions = conn.execute(f"DELETE FROM questions WHERE id IN ({placeholders}) AND status != 'active'", ids).rowcount
    result.update(deletedQuestions=questions, deletedAttempts=attempts, deletedRevisions=revisions)
    return result
