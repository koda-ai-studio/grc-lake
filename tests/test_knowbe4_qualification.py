"""A short list and a hidden legacy fallback are not cursor qualification."""

import json

from tools.qualify_knowbe4 import qualify

from test_knowbe4_connector import TOKEN, _fake_api, _next_link, _query, _users


def test_multpage_receipt_excludes_provider_data(monkeypatch):
    users = _users(501)
    _fake_api(
        monkeypatch,
        lambda req: (users[:500], _next_link("private-cursor")) if _query(req)["cursor"] == ["0"] else users[500:],
    )
    result = qualify("eu", TOKEN, "users", expected_count=501, min_interval=0)
    assert result["status"] == "qualified"
    assert result["rows"] == 501
    assert len(result["pages"]) == 2
    serialized = json.dumps(result)
    assert TOKEN not in serialized and "private-cursor" not in serialized and "example.com" not in serialized


def test_count_mismatch_and_single_page_do_not_qualify(monkeypatch):
    _fake_api(monkeypatch, lambda _: _users(3))
    assert qualify("eu", TOKEN, "users", expected_count=501, min_interval=0)["status"] == "not_qualified"


def test_unknown_cursor_response_retains_failure_receipt(monkeypatch):
    seen = _fake_api(monkeypatch, lambda _: _users(500))
    result = qualify("eu", TOKEN, "users", expected_count=501, min_interval=0)
    assert result["status"] == "incomplete"
    assert result["error_type"] == "KnowBe4PaginationError"
    assert len(seen) == 1


def test_page_budget_exhaustion_is_retained_as_incomplete(monkeypatch):
    users = _users(1000)
    _fake_api(
        monkeypatch,
        lambda req: (
            (users[:500], _next_link("c1")) if _query(req)["cursor"] == ["0"] else (users[500:], _next_link("c2"))
        ),
    )
    result = qualify("eu", TOKEN, "users", expected_count=1500, min_interval=0, max_pages=2)
    assert result["status"] == "incomplete"
    assert result["error_type"] == "IncompleteCollectionError"
    assert len(result["pages"]) == 2


def test_unresolvable_secret_stops_before_any_provider_call(monkeypatch, tmp_path):
    import pytest
    from tools import qualify_knowbe4

    monkeypatch.setattr(
        "sys.argv",
        [
            "qualify",
            "--region",
            "us",
            "--collection",
            "users",
            "--expected-count",
            "501",
            "--out",
            str(tmp_path / "receipt.json"),
        ],
    )

    def rejected(*args, **kwargs):
        raise ValueError("secret-location-must-not-be-printed")

    monkeypatch.setattr(qualify_knowbe4, "resolve_secret_ref", rejected)
    monkeypatch.setattr(qualify_knowbe4, "qualify", lambda *a, **k: pytest.fail("provider called after secret failure"))
    with pytest.raises(SystemExit) as exc:
        qualify_knowbe4.main()
    assert exc.value.code == 2
    assert not (tmp_path / "receipt.json").exists()
