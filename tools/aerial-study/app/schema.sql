-- Aerial Study Guard — SQLite schema (Schema version 1)
--
-- Design notes:
--  * questions are generic: `type` is the discriminator, type-specific data lives
--    in `options_json` / `meta_json` so future math/text types need no migration.
--  * every content edit is snapshotted into question_revisions; the questions
--    table always mirrors the latest revision.
--  * materials are content-addressed by sha256; images are served by sha256.
--  * AI generation writes draft questions only and records every job.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS materials (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256       TEXT    NOT NULL UNIQUE,
    kind         TEXT    NOT NULL DEFAULT 'image',   -- image | pdf | text (future)
    title        TEXT    NOT NULL DEFAULT '',
    filename     TEXT    NOT NULL DEFAULT '',
    content_type TEXT    NOT NULL DEFAULT '',
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    rel_path     TEXT    NOT NULL,                   -- path relative to its root dir
    status       TEXT    NOT NULL DEFAULT 'active',  -- active | disabled
    meta_json    TEXT    NOT NULL DEFAULT '{}',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT    NOT NULL DEFAULT 'word_image', -- word_image | math | text (future)
    lang         TEXT    NOT NULL DEFAULT 'zh',         -- zh | en
    prompt       TEXT    NOT NULL,
    answer       TEXT    NOT NULL,
    image_id     TEXT,                                  -- materials.sha256 (nullable)
    options_json TEXT    NOT NULL DEFAULT '[]',         -- generic type-specific options
    explanation  TEXT    NOT NULL DEFAULT '',
    difficulty   INTEGER NOT NULL DEFAULT 1,
    status       TEXT    NOT NULL DEFAULT 'draft',      -- draft | reviewed | active | disabled
    revision     INTEGER NOT NULL DEFAULT 1,
    source       TEXT    NOT NULL DEFAULT 'manual',     -- manual | ai
    meta_json    TEXT    NOT NULL DEFAULT '{}',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);
CREATE INDEX IF NOT EXISTS idx_questions_image ON questions(image_id);
CREATE INDEX IF NOT EXISTS idx_questions_updated ON questions(updated_at);

CREATE TABLE IF NOT EXISTS question_revisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    revision        INTEGER NOT NULL,
    type            TEXT    NOT NULL,
    lang            TEXT    NOT NULL,
    prompt          TEXT    NOT NULL,
    answer          TEXT    NOT NULL,
    image_id        TEXT,
    options_json    TEXT    NOT NULL DEFAULT '[]',
    explanation     TEXT    NOT NULL DEFAULT '',
    difficulty      INTEGER NOT NULL DEFAULT 1,
    status          TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT 'manual',
    changed_by      TEXT    NOT NULL DEFAULT 'admin',
    change_note     TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    UNIQUE(question_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_revisions_question ON question_revisions(question_id);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id           TEXT PRIMARY KEY,
    provider     TEXT    NOT NULL,
    model        TEXT    NOT NULL DEFAULT '',
    material_id  TEXT,
    kind         TEXT    NOT NULL DEFAULT 'word_image',
    lang         TEXT    NOT NULL DEFAULT 'zh',
    count        INTEGER NOT NULL DEFAULT 5,
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending | running | succeeded | failed
    error        TEXT    NOT NULL DEFAULT '',
    result_json  TEXT    NOT NULL DEFAULT '{}',
    requested_by TEXT    NOT NULL DEFAULT 'admin',
    created_at   TEXT    NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_created ON generation_jobs(created_at);

CREATE TABLE IF NOT EXISTS quiz_sessions (
    id                TEXT PRIMARY KEY,
    device_id         TEXT    NOT NULL DEFAULT '',
    status            TEXT    NOT NULL DEFAULT 'active', -- active | finished
    question_ids_json TEXT    NOT NULL,
    current_index     INTEGER NOT NULL DEFAULT 0,
    correct_count     INTEGER NOT NULL DEFAULT 0,
    wrong_count       INTEGER NOT NULL DEFAULT 0,
    restarts          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    expires_at        TEXT    NOT NULL,
    finished_at       TEXT
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT    NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_id       INTEGER NOT NULL,
    attempt_no        INTEGER NOT NULL,
    transcript        TEXT    NOT NULL DEFAULT '',
    correct           INTEGER NOT NULL DEFAULT 0,
    judge_method      TEXT    NOT NULL DEFAULT 'exact', -- exact | ai
    judge_detail_json TEXT    NOT NULL DEFAULT '{}',
    created_at        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_session ON quiz_attempts(session_id);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repeat_sessions (
    id                TEXT PRIMARY KEY,
    device_id         TEXT    NOT NULL DEFAULT '',
    status            TEXT    NOT NULL DEFAULT 'active',
    card_ids_json     TEXT    NOT NULL,
    current_index     INTEGER NOT NULL DEFAULT 0,
    scores_json       TEXT    NOT NULL DEFAULT '[]',
    total_score       INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    finished_at       TEXT
);

CREATE TABLE IF NOT EXISTS repeat_attempts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    card_id             INTEGER NOT NULL,
    attempt_no          INTEGER NOT NULL,
    score               INTEGER NOT NULL DEFAULT 0,
    verdict             TEXT    NOT NULL DEFAULT '',
    heard               TEXT    NOT NULL DEFAULT '',
    feedback            TEXT    NOT NULL DEFAULT '',
    pronunciation_json  TEXT    NOT NULL DEFAULT '{}',
    provider            TEXT    NOT NULL DEFAULT '',
    model               TEXT    NOT NULL DEFAULT '',
    created_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_repeat_attempts_session ON repeat_attempts(session_id);
