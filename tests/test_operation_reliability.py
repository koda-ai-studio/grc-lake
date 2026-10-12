"""API backpressure and recovery remain bounded, explicit and tenant-scoped."""

import urllib.error

import pytest
from fastapi.testclient import TestClient

from security_lakehouse.server_app import create_app


def test_rate_backend_failure_is_sanitized_503(tmp_path):
    app = create_app(tmp_path, require_auth=False)

    class Broken:
        enabled = True

        def check(self, key):
            raise ConnectionError("secret redis URL")

    app.state.rate_limiter = Broken()
    response = TestClient(app).get("/api/v1/operations")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["errors"][0]["code"] == "rate_limit_unavailable"
    assert "secret" not in response.text


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_rate_limit_configuration_is_rejected(value):
    from security_lakehouse.auth.rate_limit import RateLimitConfig

    with pytest.raises(ValueError, match="finite"):
        RateLimitConfig.from_env({"GRC_LAKE_API_RATE_LIMIT_RPS": value})


def test_cursor_pagination_does_not_repeat_jobs_after_new_insert(tmp_path):
    from security_lakehouse.auth.dependencies import _INSECURE_IDENTITY

    app = create_app(tmp_path, require_auth=False)
    queue = app.state.operation_queue
    for i in range(3):
        queue.enqueue(_INSECURE_IDENTITY, "/api/v1/snapshots", {}, str(i))
    client = TestClient(app)
    first = client.get("/api/v1/operations?limit=2").json()
    cursor = first["meta"]["pagination"]["next_cursor"]
    assert cursor
    queue.enqueue(_INSECURE_IDENTITY, "/api/v1/snapshots", {}, "new")
    second = client.get("/api/v1/operations", params={"limit": 2, "cursor": cursor}).json()
    assert len(second["data"]) == 1
    assert not {x["id"] for x in first["data"]} & {x["id"] for x in second["data"]}
    assert second["meta"]["pagination"]["next_cursor"] is None
    assert client.get("/api/v1/operations?cursor=invalid").status_code == 400


def test_retry_after_larger_than_budget_does_not_retry_early():
    from security_lakehouse.ingestion.backoff import http_retry

    sleeps = []
    calls = []
    error = urllib.error.HTTPError("https://example.test", 429, "limited", {"Retry-After": "300"}, None)

    def fail():
        calls.append(1)
        raise error

    with pytest.raises(urllib.error.HTTPError):
        http_retry(fail, max_retries=2, cap=10, sleep=sleeps.append)
    assert calls == [1]
    assert sleeps == []


def test_repeated_cursor_is_detected_without_exhausting_budget():
    from security_lakehouse.ingestion.paginate import IncompleteCollectionError, paginate

    calls = []

    def fetch(cursor):
        calls.append(cursor)
        return {"next": "sensitive-cursor"}

    with pytest.raises(IncompleteCollectionError) as exc:
        list(paginate(fetch, lambda page: [], lambda page: page["next"], max_pages=100))
    assert len(calls) == 2
    assert "sensitive-cursor" not in str(exc.value)


def test_redis_budget_uses_server_clock_and_expires_idle_keys():
    from security_lakehouse.auth.rate_limit import RateLimitConfig
    from security_lakehouse.auth.rate_limit_redis import RedisRateLimiter

    class Store:
        def eval(self, script, count, *args):
            assert "redis.call('TIME')" in script
            assert "redis.call('PEXPIRE'" in script
            # Replica monotonic clocks must not be part of the shared budget.
            assert len(args) == 4
            return [0, "0.25"]

    limiter = RedisRateLimiter(RateLimitConfig(), "redis://unused", client=Store())
    assert limiter.check("credential") == (False, 0.25)


def test_stale_generation_returns_conflict_without_publication(tmp_path):
    from security_lakehouse.pipeline import run_pipeline

    run_pipeline("data/raw/security_events.jsonl", tmp_path)
    before = (tmp_path / ".active-generation").readlink()
    app = create_app(tmp_path, require_auth=False)
    response = TestClient(app).post("/api/v1/ingestion/eval", json={"expected_generation": "0" * 32})
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "generation_conflict"
    assert (tmp_path / ".active-generation").readlink() == before
