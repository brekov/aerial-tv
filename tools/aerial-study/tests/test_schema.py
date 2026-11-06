"""SQLite schema, revision snapshots and generic question support."""

from __future__ import annotations

import sqlite3

EXPECTED_TABLES = {
    "materials",
    "questions",
    "question_revisions",
    "generation_jobs",
    "quiz_sessions",
    "quiz_attempts",
    "settings",
}

EXPECTED_COLUMNS = {
    "materials": {"id", "sha256", "kind", "title", "rel_path", "status", "created_at"},
    "questions": {
        "id",
        "type",
        "lang",
        "prompt",
        "answer",
        "image_id",
        "options_json",
        "status",
        "revision",
        "source",
    },
    "question_revisions": {
        "question_id",
        "revision",
        "prompt",
        "answer",
        "status",
        "changed_by",
        "change_note",
    },
    "generation_jobs": {"id", "provider", "status", "count", "result_json", "error"},
    "quiz_sessions": {
        "id",
        "status",
        "question_ids_json",
        "current_index",
        "correct_count",
        "wrong_count",
        "restarts",
        "expires_at",
    },
    "quiz_attempts": {
        "session_id",
        "question_id",
        "attempt_no",
        "transcript",
        "correct",
        "judge_method",
    },
}


def _conn(app):
    conn = sqlite3.connect(app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_all_tables_and_columns_exist(app):
    conn = _conn(app)
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert EXPECTED_TABLES.issubset(tables)
        for table, expected in EXPECTED_COLUMNS.items():
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            missing = expected - columns
            assert not missing, f"{table} missing {missing}"
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 1
    finally:
        conn.close()


def test_question_creation_snapshots_first_revision(admin_client, image_factory):
    image = image_factory()
    response = admin_client.post(
        "/api/v1/admin/questions",
        json={
            "prompt": "What is this?",
            "answer": "apple",
            "imageId": image["sha256"],
            "lang": "en",
        },
    )
    assert response.status_code == 201
    question = response.json()["question"]
    assert question["status"] == "draft"
    assert question["revision"] == 1

    detail = admin_client.get(f"/api/v1/admin/questions/{question['id']}").json()
    assert len(detail["revisions"]) == 1
    assert detail["revisions"][0]["revision"] == 1
    assert detail["revisions"][0]["prompt"] == "What is this?"
    assert detail["revisions"][0]["answer"] == "apple"


def test_edits_create_revisions_and_keep_history(admin_client, image_factory):
    image = image_factory()
    created = admin_client.post(
        "/api/v1/admin/questions",
        json={"prompt": "Old prompt", "answer": "old", "imageId": image["sha256"]},
    ).json()["question"]
    question_id = created["id"]

    updated = admin_client.patch(
        f"/api/v1/admin/questions/{question_id}",
        json={"prompt": "New prompt", "answer": "new", "changeNote": "fix typo"},
    )
    assert updated.status_code == 200
    assert updated.json()["question"]["revision"] == 2

    activated = admin_client.post(
        f"/api/v1/admin/questions/{question_id}/status", json={"status": "active"}
    )
    assert activated.status_code == 200
    assert activated.json()["question"]["status"] == "active"
    assert activated.json()["question"]["revision"] == 3

    revisions = admin_client.get(f"/api/v1/admin/questions/{question_id}/revisions").json()[
        "revisions"
    ]
    assert [item["revision"] for item in revisions] == [3, 2, 1]
    assert revisions[-1]["prompt"] == "Old prompt"
    assert revisions[-1]["answer"] == "old"
    assert revisions[1]["prompt"] == "New prompt"
    assert revisions[1]["changeNote"] == "fix typo"
    assert revisions[0]["status"] == "active"


def test_activation_requires_image_for_word_image(admin_client, image_factory):
    image = image_factory()
    created = admin_client.post(
        "/api/v1/admin/questions",
        json={"prompt": "No image", "answer": "x"},
    ).json()["question"]
    response = admin_client.post(
        f"/api/v1/admin/questions/{created['id']}/status", json={"status": "active"}
    )
    assert response.status_code == 422
    assert "without an image" in response.json()["detail"]

    attached = admin_client.patch(
        f"/api/v1/admin/questions/{created['id']}",
        json={"imageId": image["sha256"]},
    )
    assert attached.status_code == 200
    response = admin_client.post(
        f"/api/v1/admin/questions/{created['id']}/status", json={"status": "active"}
    )
    assert response.status_code == 200


def test_generic_schema_supports_future_math_type(admin_client):
    response = admin_client.post(
        "/api/v1/admin/questions",
        json={
            "type": "math",
            "prompt": "1 + 1 = ?",
            "answer": "2",
            "options": ["1", "2", "3"],
            "status": "active",
        },
    )
    assert response.status_code == 201
    question = response.json()["question"]
    assert question["type"] == "math"
    assert question["options"] == ["1", "2", "3"]
    assert question["status"] == "active"
    assert question["imageId"] is None


def test_history_endpoint_lists_recent_revisions(admin_client, image_factory):
    image = image_factory()
    for index in range(3):
        admin_client.post(
            "/api/v1/admin/questions",
            json={
                "prompt": f"history {index}",
                "answer": str(index),
                "imageId": image["sha256"],
            },
        )
    history = admin_client.get("/api/v1/admin/history?limit=10")
    assert history.status_code == 200
    items = history.json()["items"]
    assert len(items) >= 3
    assert items[0]["revision"] == 1
    assert items[0]["prompt"].startswith("history ")
