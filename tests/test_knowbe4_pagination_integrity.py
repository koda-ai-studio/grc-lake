"""Incomplete or overlapping provider lists must not become successful evidence."""

import pytest

from security_lakehouse.connectors_knowbe4 import KnowBe4PaginationError
from test_knowbe4_connector import TOKEN, _client, _fake_api, _next_link, _query, _users


def test_overlapping_pages_fail_closed(monkeypatch):
    monkeypatch.setattr("security_lakehouse.connectors_knowbe4.PER_PAGE", 3)
    users = _users(4)

    def respond(request):
        query = _query(request)
        return (users[:3], _next_link("next")) if query["cursor"] == ["0"] else users[2:]

    _fake_api(monkeypatch, respond)
    with pytest.raises(KnowBe4PaginationError, match="repeated record"):
        _client().users()


@pytest.mark.parametrize(
    ("method", "identity"),
    [("users", "id"), ("training_enrollments", "enrollment_id"), ("phishing_tests", "pst_id")],
)
def test_full_page_without_cursor_never_uses_deprecated_paging(monkeypatch, method, identity):
    monkeypatch.setattr("security_lakehouse.connectors_knowbe4.PER_PAGE", 3)
    rows = [{identity: i} for i in range(3)]
    # A legacy server could complete the list, but migration must never send page=.
    requests = _fake_api(monkeypatch, lambda r: [] if "page" in _query(r) else rows)
    with pytest.raises(KnowBe4PaginationError, match="no next cursor"):
        getattr(_client(), method)()
    assert len(requests) == 1
    assert "page" not in _query(requests[0])


@pytest.mark.parametrize("query", ["page=2", "cursor=", "cursor=%20", "cursor=a&cursor=b"])
def test_unusable_next_link_on_short_page_is_incomplete(monkeypatch, query):
    requests = _fake_api(
        monkeypatch,
        lambda _: (_users(1), {"Link": f'<https://eu.api.knowbe4.com/v1/users?{query}>; rel="next"'}),
    )
    with pytest.raises(KnowBe4PaginationError, match="next link") as caught:
        _client().users()
    assert len(requests) == 1
    assert query not in str(caught.value)
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("rows", [[None], [{"email": "missing-id@example.test"}]])
def test_malformed_rows_are_not_silently_dropped(monkeypatch, rows):
    _fake_api(monkeypatch, lambda _: rows)
    with pytest.raises(KnowBe4PaginationError, match="record identity"):
        _client().users()


@pytest.mark.parametrize("failing_path", ["/v1/users", "/v1/training/enrollments", "/v1/phishing/security_tests"])
def test_incomplete_cursor_sync_preserves_published_evidence(tmp_path, monkeypatch, failing_path):
    from urllib.parse import urlsplit

    from security_lakehouse import connector_runner
    from security_lakehouse.connector_state import append_config_event, latest_run
    from security_lakehouse.ingestion.watermark import read_watermark, write_watermark
    from test_knowbe4_connector import FIXTURE

    append_config_event(
        tmp_path,
        connector_id="knowbe4-training",
        state="enabled",
        actor="alice",
        credentials={"region": "eu", "credential_ref": "KB4_TOKEN"},
    )
    connector_runner.run_connector_sync(tmp_path, connector_id="knowbe4-training", fixture_dir=FIXTURE)
    raw = tmp_path / connector_runner.CONNECTOR_RAW_FILE
    posture = tmp_path / "gold/current_posture.json"
    raw_before, posture_before = raw.read_bytes(), posture.read_bytes()
    write_watermark(tmp_path, "knowbe4-training", "previous")
    monkeypatch.setenv("KB4_TOKEN", TOKEN)
    monkeypatch.setattr("security_lakehouse.connectors_knowbe4.PER_PAGE", 3)
    monkeypatch.setattr("security_lakehouse.connectors_knowbe4.KnowBe4Client._pace", lambda _: None)
    identity = {"/v1/users": "id", "/v1/training/enrollments": "enrollment_id", "/v1/phishing/security_tests": "pst_id"}

    def respond(request):
        path = urlsplit(request.full_url).path
        return [{identity[path]: i} for i in range(3)] if path == failing_path else []

    requests = _fake_api(monkeypatch, respond)
    with pytest.raises(connector_runner.ConnectorSyncError, match="no next cursor") as caught:
        connector_runner.run_connector_sync(tmp_path, connector_id="knowbe4-training")
    assert TOKEN not in str(caught.value)
    assert latest_run(tmp_path, "knowbe4-training", kind="sync")["result"] == "error"
    assert all("page" not in _query(r) for r in requests)
    assert raw.read_bytes() == raw_before
    assert posture.read_bytes() == posture_before
    assert read_watermark(tmp_path, "knowbe4-training") == "previous"
