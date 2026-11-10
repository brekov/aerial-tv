"""Five-question session lifecycle: selection, progress, wrong-answer restart."""

from __future__ import annotations

import json
import sqlite3


def _answer(tv_client, session_id, question_id, transcript):
    return tv_client.post(
        f"/api/v1/sessions/{session_id}/answer",
        json={"questionId": question_id, "transcript": transcript},
    )


def _create_session(tv_client):
    response = tv_client.post("/api/v1/sessions", json={})
    assert response.status_code == 201, response.text
    return response.json()


def test_requires_enough_active_questions(tv_client, question_factory):
    question_factory(4, prefix="few")
    response = tv_client.post("/api/v1/sessions", json={})
    assert response.status_code == 409
    assert "need 5" in response.json()["detail"]

    question_factory(1, prefix="extra")
    assert tv_client.post("/api/v1/sessions", json={}).status_code == 201


def test_selection_uses_only_active_unique_questions(tv_client, question_factory):
    active = question_factory(6, prefix="active")
    drafts = question_factory(2, status="draft", prefix="draft")
    session = _create_session(tv_client)
    questions = session["questions"]
    assert len(questions) == 5
    ids = [question["id"] for question in questions]
    assert len(set(ids)) == 5
    assert set(ids).issubset(set(active["ids"]))
    assert not set(ids) & set(drafts["ids"])
    assert session["session"]["status"] == "active"
    assert session["expiresAt"] == session["session"]["expiresAt"]
    for question in questions:
        assert set(question.keys()) == {
            "id",
            "type",
            "prompt",
            "imageUrl",
            "say",
            "lang",
            "difficulty",
        }
        assert "?s=" in question["imageUrl"]


def test_session_payload_has_no_answer_field(tv_client, seeded):
    # Repeat-after-me intentionally sends the target pronunciation as `say`.
    session = _create_session(tv_client)
    assert all("answer" not in question for question in session["questions"])
    assert all(question.get("say") for question in session["questions"])


def test_correct_answer_advances_progress(tv_client, seeded):
    session = _create_session(tv_client)
    session_id = session["session"]["id"]
    first = session["questions"][0]
    response = _answer(tv_client, session_id, first["id"], seeded["answers"][first["id"]])
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is True
    assert body["restart"] is False
    assert body["finished"] is False
    assert body["progress"]["currentIndex"] == 1
    assert body["progress"]["correct"] == 1
    assert body["nextQuestion"]["id"] == session["questions"][1]["id"]

    view = tv_client.get(f"/api/v1/sessions/{session_id}").json()
    assert view["progress"]["currentIndex"] == 1
    assert view["session"]["status"] == "active"


def test_wrong_answer_restarts_the_same_run(tv_client, seeded):
    session = _create_session(tv_client)
    session_id = session["session"]["id"]
    first = session["questions"][0]

    response = _answer(tv_client, session_id, first["id"], "definitely wrong")
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is False
    assert body["restart"] is True
    assert body["finished"] is False
    assert body["progress"]["currentIndex"] == 0
    assert body["progress"]["wrong"] == 1
    assert body["progress"]["restarts"] == 1

    # The same first question is asked again; a correct answer advances.
    response = _answer(tv_client, session_id, first["id"], seeded["answers"][first["id"]])
    assert response.status_code == 200
    assert response.json()["correct"] is True
    assert response.json()["progress"]["currentIndex"] == 1

    attempts = _admin_attempts(tv_client, session_id)
    assert len(attempts) == 2
    assert attempts[0]["correct"] is False
    assert attempts[1]["correct"] is True


def _admin_attempts(_tv_client, session_id):
    # The session detail lives behind admin auth; use a fresh admin client.
    from fastapi.testclient import TestClient

    from tests.conftest import ADMIN_PASSWORD

    app = _tv_client.app
    client = TestClient(app)
    client.post("/admin/login", data={"password": ADMIN_PASSWORD})
    return client.get(f"/api/v1/admin/sessions/{session_id}").json()["attempts"]


def test_finish_after_five_correct_answers(tv_client, seeded):
    session = _create_session(tv_client)
    session_id = session["session"]["id"]
    for index, question in enumerate(session["questions"]):
        response = _answer(tv_client, session_id, question["id"], seeded["answers"][question["id"]])
        assert response.status_code == 200
        body = response.json()
        assert body["correct"] is True
        assert body["finished"] is (index == 4)
        assert body["progress"]["currentIndex"] == index + 1

    view = tv_client.get(f"/api/v1/sessions/{session_id}").json()
    assert view["session"]["status"] == "finished"
    assert view["finished"] is True
    assert view["progress"]["total"] == 5

    # No more answers are accepted after finishing.
    response = _answer(
        tv_client,
        session_id,
        session["questions"][0]["id"],
        seeded["answers"][session["questions"][0]["id"]],
    )
    assert response.status_code == 409

    attempts = _admin_attempts(tv_client, session_id)
    assert len(attempts) == 5
    assert all(attempt["correct"] for attempt in attempts)


def test_out_of_order_answer_is_rejected(tv_client, seeded):
    session = _create_session(tv_client)
    session_id = session["session"]["id"]
    second = session["questions"][1]
    response = _answer(tv_client, session_id, second["id"], seeded["answers"][second["id"]])
    assert response.status_code == 409
    assert "expected question" in response.json()["detail"]


def test_answer_normalisation_accepts_case_and_punctuation(tv_client, seeded):
    session = _create_session(tv_client)
    session_id = session["session"]["id"]
    first = session["questions"][0]
    transcript = f"  {seeded['answers'][first['id']].upper()}!!  "
    response = _answer(tv_client, session_id, first["id"], transcript)
    assert response.status_code == 200
    assert response.json()["correct"] is True


def test_expired_session_is_rejected(tv_client, seeded, app):
    session = _create_session(tv_client)
    session_id = session["session"]["id"]
    conn = sqlite3.connect(app.state.settings.db_path)
    try:
        conn.execute(
            "UPDATE quiz_sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (session_id,),
        )
        conn.commit()
    finally:
        conn.close()

    assert tv_client.get(f"/api/v1/sessions/{session_id}").status_code == 410
    first = session["questions"][0]
    assert (
        _answer(tv_client, session_id, first["id"], seeded["answers"][first["id"]]).status_code
        == 410
    )


def test_image_url_is_session_scoped(tv_client, client, admin_client, seeded):
    session = _create_session(tv_client)
    image_url = session["questions"][0]["imageUrl"]
    assert image_url.startswith("/api/v1/images/")

    # A session id in ?s= is a capability usable without a token.
    assert client.get(image_url).status_code == 200
    # The plain URL is denied for anonymous callers.
    bare_url = image_url.split("?")[0]
    assert client.get(bare_url).status_code == 401
    # Device token and admin cookie are also accepted.
    assert tv_client.get(bare_url).status_code == 200
    assert admin_client.get(bare_url).status_code == 200
    # Unknown image ids are 404 for authorized callers.
    assert tv_client.get("/api/v1/images/" + "0" * 64).status_code == 404


def test_unknown_session_is_404(tv_client):
    response = tv_client.get("/api/v1/sessions/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"
