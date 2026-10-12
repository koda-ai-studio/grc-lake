"""Incomplete or overlapping provider lists must not become successful evidence."""

import pytest

from security_lakehouse.connectors_knowbe4 import KnowBe4Client, KnowBe4PaginationError
from test_knowbe4_connector import TOKEN, _client, _fake_api, _next_link, _query, _users


@pytest.mark.parametrize("cursor_mode", [True, False])
def test_overlapping_pages_fail_closed(monkeypatch, cursor_mode):
    monkeypatch.setattr("security_lakehouse.connectors_knowbe4.PER_PAGE", 3)
    users = _users(4)

    def respond(request):
        query = _query(request)
        if cursor_mode:
            return (users[:3], _next_link("next")) if query["cursor"] == ["0"] else users[2:]
        return users[2:] if query.get("page") == ["2"] else users[:3]

    _fake_api(monkeypatch, respond)
    with pytest.raises(KnowBe4PaginationError, match="repeated record"):
        _client().users()


def test_cursor_only_qualification_never_uses_legacy_fallback(monkeypatch):
    monkeypatch.setattr("security_lakehouse.connectors_knowbe4.PER_PAGE", 3)
    requests = _fake_api(monkeypatch, lambda _: _users(3))
    client = KnowBe4Client("eu", token=TOKEN, min_interval=0, allow_legacy_paging=False)
    with pytest.raises(KnowBe4PaginationError, match="no next cursor"):
        client.users()
    assert len(requests) == 1
    assert "page" not in _query(requests[0])


@pytest.mark.parametrize("rows", [[None], [{"email": "missing-id@example.test"}]])
def test_malformed_rows_are_not_silently_dropped(monkeypatch, rows):
    _fake_api(monkeypatch, lambda _: rows)
    with pytest.raises(KnowBe4PaginationError, match="record identity"):
        _client().users()
