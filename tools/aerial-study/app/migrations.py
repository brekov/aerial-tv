"""Idempotent schema migrations for the study service."""
from __future__ import annotations

import sqlite3
from typing import Iterable

NEW_TABLES = """
CREATE TABLE IF NOT EXISTS age_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_types (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  answer_mode TEXT NOT NULL DEFAULT 'voice',
  requires_image INTEGER NOT NULL DEFAULT 0,
  requires_material INTEGER NOT NULL DEFAULT 0,
  min_options INTEGER NOT NULL DEFAULT 0,
  max_options INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS material_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  parent_id INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mobile_upload_tokens (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  max_uploads INTEGER NOT NULL DEFAULT 10,
  used_count INTEGER NOT NULL DEFAULT 0,
  category_id INTEGER,
  age_group_id INTEGER,
  subject_id INTEGER,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'tv'
);
CREATE INDEX IF NOT EXISTS idx_mobile_tokens_hash ON mobile_upload_tokens(token_hash);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def migrate_v2(conn: sqlite3.Connection, now: str) -> None:
    conn.executescript(NEW_TABLES)
    for table in ("questions", "question_revisions"):
        _add(conn, table, "age_group_id", "INTEGER")
        _add(conn, table, "subject_id", "INTEGER")
        _add(conn, table, "answer_mode", "TEXT NOT NULL DEFAULT 'voice'")
    _add(conn, "questions", "deleted_at", "TEXT")
    for table in ("materials",):
        _add(conn, table, "category_id", "INTEGER")
        _add(conn, table, "age_group_id", "INTEGER")
        _add(conn, table, "subject_id", "INTEGER")
        _add(conn, table, "source", "TEXT NOT NULL DEFAULT 'upload'")
        _add(conn, table, "source_path", "TEXT NOT NULL DEFAULT ''")
    for table in ("generation_jobs",):
        _add(conn, table, "question_type", "TEXT NOT NULL DEFAULT 'word_image'")
        _add(conn, table, "age_group_id", "INTEGER")
        _add(conn, table, "subject_id", "INTEGER")
        _add(conn, table, "answer_mode", "TEXT NOT NULL DEFAULT 'voice'")
        _add(conn, table, "params_json", "TEXT NOT NULL DEFAULT '{}'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_deleted ON questions(deleted_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_age ON questions(age_group_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_question ON quiz_attempts(question_id)")
    seed_taxonomy(conn, now)
    conn.execute("UPDATE questions SET answer_mode = 'voice' WHERE answer_mode IS NULL OR answer_mode = ''")
    conn.execute("UPDATE materials SET source = 'upload' WHERE source IS NULL OR source = ''")


def seed_taxonomy(conn: sqlite3.Connection, now: str) -> None:
    ages: Iterable[tuple[str, str, int]] = (
        ("unclassified", "未分类", 0),
        ("preschool", "学前", 10),
        ("grade1", "一年级", 20),
        ("grade2", "二年级", 30),
        ("grade3", "三年级", 40),
        ("grade4", "四年级", 50),
        ("grade5", "五年级", 60),
        ("grade6", "六年级", 70),
    )
    for code, name, order in ages:
        conn.execute(
            "INSERT OR IGNORE INTO age_groups(code, name, sort_order, active, created_at) VALUES(?,?,?,1,?)",
            (code, name, order, now),
        )
    subjects: Iterable[tuple[str, str, int]] = (
        ("unclassified", "未分类", 0),
        ("literacy", "识字", 10),
        ("english", "英语", 20),
        ("math", "数学", 30),
        ("logic", "逻辑", 40),
        ("general", "常识", 50),
    )
    for code, name, order in subjects:
        conn.execute(
            "INSERT OR IGNORE INTO subjects(code, name, sort_order, active, created_at) VALUES(?,?,?,1,?)",
            (code, name, order, now),
        )
    categories = (("未分类", 0), ("教材图片", 10), ("识字卡", 20), ("数学题", 30), ("英语单词卡", 40))
    for name, order in categories:
        conn.execute(
            "INSERT INTO material_categories(name, parent_id, sort_order, active, created_at) "
            "SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM material_categories WHERE name = ?)",
            (name, None, order, 1, now, name),
        )
    types = (
        ("word_image", "看图跟读", "voice", 1, 1, 0, 0, 10),
        ("word_image_choice", "看图选词", "choice", 1, 1, 2, 4, 20),
        ("text_choice", "文字选择", "choice", 0, 0, 2, 4, 30),
        ("math_choice", "算术选择", "choice", 0, 0, 2, 4, 40),
    )
    for code, name, mode, image, material, mino, maxo, order in types:
        conn.execute(
            "INSERT OR IGNORE INTO question_types(code,name,answer_mode,requires_image,requires_material,min_options,max_options,active,sort_order) "
            "VALUES(?,?,?,?,?,?,?,1,?)",
            (code, name, mode, image, material, mino, maxo, order),
        )
