"""Unit tests for text normalisation and redaction helpers."""

from __future__ import annotations

from app.sessions import SessionError
from app.util import normalize_answer, redact, split_accepted_answers


def test_normalize_answer_handles_cjk_and_punctuation():
    assert normalize_answer("  Hello, world!  ") == "helloworld"
    assert normalize_answer("苹果。") == "苹果"
    assert normalize_answer("ＡＰＰＬＥ") == "apple"  # full-width -> NFKC
    assert normalize_answer("") == ""
    assert normalize_answer(None) == ""


def test_split_accepted_answers():
    assert split_accepted_answers("apple|apples") == ["apple", "apples"]
    assert split_accepted_answers("苹果\n苹果树") == ["苹果", "苹果树"]
    assert split_accepted_answers(" | ") == []


def test_redact_masks_key_material():
    text = 'Authorization: Bearer sk-secret-value, api_key="abc123"'
    masked = redact(text)
    assert "sk-secret-value" not in masked
    assert "abc123" not in masked
    assert "***" in masked


def test_session_error_carries_status_code():
    error = SessionError("nope", status_code=410)
    assert error.message == "nope"
    assert error.status_code == 410
    assert str(error) == "nope"


def test_match_answer_is_exact_and_forgiving():
    from app.util import match_answer

    assert match_answer(["bear"], "Bear.")[0:2] == (True, "exact")
    assert match_answer(["bear"], "beers")[0] is False
    # One-edit near miss for a longer Latin word is accepted.
    assert match_answer(["apple"], "apples")[0:2] == (True, "fuzzy")
    assert match_answer(["apple"], "appl")[0:2] == (True, "fuzzy")
    # Short words stay strict.
    assert match_answer(["cat"], "bat")[0] is False
    # Unrelated words are rejected.
    assert match_answer(["lion"], "tiger")[0] is False


def test_match_answer_accepts_chinese_homophones_and_fillers():
    import pytest
    pytest.importorskip("pypinyin")
    from app.util import match_answer

    assert match_answer(["苹果"], "苹果。")[0:2] == (True, "exact")
    assert match_answer(["苹果"], "平果")[0:2] == (True, "pinyin")
    assert match_answer(["苹果"], "啊，苹果")[0:2] == (True, "exact")
    assert match_answer(["苹果"], "香蕉")[0] is False
