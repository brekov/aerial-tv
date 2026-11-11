"""Read-only admin presentation models.

Keeps taxonomy names, image URLs, labels and attempt aggregates in one place
so the Vue admin never has to guess from internal codes.
"""
from __future__ import annotations

from typing import Any, Iterable

from .config import Settings
from .db import read_session
from .materials import admin_material_dict, get_image_material
from .util import safe_json_loads

STATUS_LABELS = {
    "draft": "草稿",
    "reviewed": "已审核",
    "active": "已启用",
    "disabled": "已停用",
    "deleted": "已删除",
}
MODE_LABELS = {"voice": "跟读", "choice": "选择"}


def taxonomy_maps(settings: Settings) -> dict[str, dict[Any, str]]:
    with read_session(settings) as conn:
        ages = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM age_groups")}
        subjects = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM subjects")}
        categories = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM material_categories")}
        types = {
            row["code"]: dict(row)
            for row in conn.execute("SELECT * FROM question_types")
        }
    return {"age": ages, "subject": subjects, "category": categories, "type": types}


def attempt_stats(settings: Settings, question_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    ids = [int(value) for value in question_ids]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with read_session(settings) as conn:
        rows = conn.execute(
            f"""
            SELECT question_id, COUNT(*) AS attempts,
                   SUM(CASE WHEN correct = 0 THEN 1 ELSE 0 END) AS wrong,
                   MAX(CASE WHEN correct = 0 THEN created_at ELSE NULL END) AS last_wrong_at
            FROM quiz_attempts
            WHERE question_id IN ({placeholders})
            GROUP BY question_id
            """,
            ids,
        ).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        total = int(row["attempts"] or 0)
        wrong = int(row["wrong"] or 0)
        out[int(row["question_id"])] = {
            "attempts": total,
            "wrong": wrong,
            "wrongRate": round(wrong / total, 3) if total else 0.0,
            "lastWrongAt": row["last_wrong_at"],
        }
    return out


def _display_title(question: dict[str, Any], answer: str, type_name: str) -> str:
    if str(question.get("type")) in {"word_image", "word_image_choice"}:
        return f"{type_name} · {answer}" if answer else type_name
    prompt = str(question.get("prompt") or "").strip()
    return prompt[:48] if prompt else type_name


def question_view(
    settings: Settings,
    question: dict[str, Any],
    maps: dict[str, dict[Any, str]] | None = None,
    stats: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    maps = maps or taxonomy_maps(settings)
    image = get_image_material(settings, str(question["image_id"])) if question.get("image_id") else None
    type_code = str(question.get("type") or "")
    type_info = maps["type"].get(type_code, {})
    type_name = str(type_info.get("name") or type_code)
    answer = str(question.get("answer") or "").split("|")[0].strip()
    stat = (stats or {}).get(int(question["id"]), {})
    image_view = admin_material_dict(settings, image) if image else None
    return {
        "id": question["id"],
        "displayTitle": _display_title(question, answer, type_name),
        "prompt": question["prompt"],
        "answer": question["answer"],
        "image": image_view,
        "imageUrl": image_view["url"] if image_view else None,
        "type": type_code,
        "typeLabel": type_name,
        "answerMode": question.get("answer_mode", "voice"),
        "answerModeLabel": MODE_LABELS.get(question.get("answer_mode", "voice"), question.get("answer_mode")),
        "options": safe_json_loads(question.get("options_json"), []),
        "ageGroup": {
            "id": question.get("age_group_id"),
            "name": maps["age"].get(question.get("age_group_id"), "未分类"),
        },
        "subject": {
            "id": question.get("subject_id"),
            "name": maps["subject"].get(question.get("subject_id"), "未分类"),
        },
        "ageGroupId": question.get("age_group_id"),
        "subjectId": question.get("subject_id"),
        "status": question.get("status"),
        "statusLabel": STATUS_LABELS.get(str(question.get("status")), str(question.get("status"))),
        "difficulty": question.get("difficulty"),
        "source": question.get("source"),
        "revision": question.get("revision"),
        "createdAt": question.get("created_at"),
        "updatedAt": question.get("updated_at"),
        "deletedAt": question.get("deleted_at"),
        "stats": stat or {"attempts": 0, "wrong": 0, "wrongRate": 0.0, "lastWrongAt": None},
    }


def questions_view(settings: Settings, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    maps = taxonomy_maps(settings)
    stats = attempt_stats(settings, [int(row["id"]) for row in rows])
    return [question_view(settings, row, maps, stats) for row in rows]


def material_view(settings: Settings, material: dict[str, Any], maps: dict[str, dict[Any, str]] | None = None) -> dict[str, Any]:
    maps = maps or taxonomy_maps(settings)
    base = admin_material_dict(settings, material)
    base["category"] = {
        "id": material.get("category_id"),
        "name": maps["category"].get(material.get("category_id"), "未分类"),
    }
    base["ageGroup"] = {
        "id": material.get("age_group_id"),
        "name": maps["age"].get(material.get("age_group_id"), "未分类"),
    }
    base["subject"] = {
        "id": material.get("subject_id"),
        "name": maps["subject"].get(material.get("subject_id"), "未分类"),
    }
    return base
