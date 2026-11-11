"""Age groups, subjects, question types and material categories."""
from __future__ import annotations

import sqlite3
from typing import Any

from .config import Settings
from .db import read_session, session
from .util import iso, utcnow


class TaxonomyError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return iso(utcnow())


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY sort_order, rowid")]


def all_taxonomy(settings: Settings) -> dict[str, Any]:
    with read_session(settings) as conn:
        return {
            "ageGroups": _rows(conn, "age_groups"),
            "subjects": _rows(conn, "subjects"),
            "questionTypes": _rows(conn, "question_types"),
            "materialCategories": _rows(conn, "material_categories"),
        }


def age_group_exists(settings: Settings, value: int | None) -> bool:
    if value is None:
        return True
    with read_session(settings) as conn:
        return conn.execute("SELECT 1 FROM age_groups WHERE id = ?", (value,)).fetchone() is not None


def subject_exists(settings: Settings, value: int | None) -> bool:
    if value is None:
        return True
    with read_session(settings) as conn:
        return conn.execute("SELECT 1 FROM subjects WHERE id = ?", (value,)).fetchone() is not None


def question_type(settings: Settings, code: str) -> dict[str, Any] | None:
    with read_session(settings) as conn:
        row = conn.execute("SELECT * FROM question_types WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None


def _table_for(kind: str) -> str:
    return {
        "age-groups": "age_groups",
        "subjects": "subjects",
        "material-categories": "material_categories",
    }[kind]


def create_item(settings: Settings, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    table = _table_for(kind)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise TaxonomyError("name is required")
    code = str(payload.get("code") or "").strip().lower()
    if kind in {"age-groups", "subjects"} and not code:
        raise TaxonomyError("code is required")
    with session(settings) as conn:
        if kind == "material-categories":
            cursor = conn.execute(
                "INSERT INTO material_categories(name, parent_id, sort_order, active, created_at) VALUES(?,?,?,?,?)",
                (name, payload.get("parentId"), int(payload.get("sortOrder") or 0), 1, _now()),
            )
            row = conn.execute("SELECT * FROM material_categories WHERE id = ?", (cursor.lastrowid,)).fetchone()
        else:
            note = {"age-groups": "age_groups", "subjects": "subjects"}[kind]
            cursor = conn.execute(
                f"INSERT INTO {note}(code, name, sort_order, active, created_at) VALUES(?,?,?,?,?)",
                (code, name, int(payload.get("sortOrder") or 0), 1, _now()),
            )
            row = conn.execute(f"SELECT * FROM {note} WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def update_item(settings: Settings, kind: str, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    table = _table_for(kind)
    fields: list[str] = []
    values: list[Any] = []
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            raise TaxonomyError("name cannot be empty")
        fields.append("name = ?"); values.append(name)
    if "sortOrder" in payload:
        fields.append("sort_order = ?"); values.append(int(payload["sortOrder"] or 0))
    if "active" in payload:
        fields.append("active = ?"); values.append(1 if payload["active"] else 0)
    if not fields:
        raise TaxonomyError("no fields to update")
    values.append(item_id)
    with session(settings) as conn:
        conn.execute(f"UPDATE {table} SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise TaxonomyError("item not found", status_code=404)
    return dict(row)


def update_question_type(settings: Settings, code: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = question_type(settings, code)
    if not current:
        raise TaxonomyError("question type not found", status_code=404)
    fields: list[str] = []
    values: list[Any] = []
    for key, column in (("name", "name"), ("answerMode", "answer_mode")):
        if key in payload:
            fields.append(f"{column} = ?"); values.append(str(payload[key]).strip())
    for key, column in (("requiresImage", "requires_image"), ("requiresMaterial", "requires_material"),
                        ("minOptions", "min_options"), ("maxOptions", "max_options"), ("active", "active")):
        if key in payload:
            fields.append(f"{column} = ?"); values.append(int(bool(payload[key])) if key in {"requiresImage", "requiresMaterial", "active"} else int(payload[key]))
    if not fields:
        raise TaxonomyError("no fields to update")
    values.append(code)
    with session(settings) as conn:
        conn.execute(f"UPDATE question_types SET {', '.join(fields)} WHERE code = ?", values)
        row = conn.execute("SELECT * FROM question_types WHERE code = ?", (code,)).fetchone()
    return dict(row)


def parse_category(settings: Settings, value: int | None) -> int | None:
    if value is None:
        return None
    with read_session(settings) as conn:
        row = conn.execute("SELECT id FROM material_categories WHERE id = ?", (value,)).fetchone()
    if not row:
        raise TaxonomyError("material category not found", status_code=404)
    return int(value)


def category_name(settings: Settings, value: int | None) -> str:
    if value is None:
        return ""
    with read_session(settings) as conn:
        row = conn.execute("SELECT name FROM material_categories WHERE id = ?", (value,)).fetchone()
    return row["name"] if row else ""
