"""Admission bound and cooperative cancellation for investigation graph builds."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")

from fastapi.testclient import TestClient

from security_lakehouse import investigation_graph as graph_module
from security_lakehouse.db.base import session_scope
from security_lakehouse.db.repository import create_api_key, create_tenant, create_user
from security_lakehouse.graph_admission import (
    BuildToken,
    GraphBuildAborted,
    GraphBuildSlots,
    graph_build_settings,
    graph_tenant_capacity,
)
from security_lakehouse.server_app import create_app
from test_api_v1 import _seed_lake

URL = "/api/v1/graph/investigation"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **settings: str):
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    _seed_lake(tmp_path)
    app = create_app(tmp_path)
    client = TestClient(app)
    with session_scope(app.state.sessionmaker) as session:
        tenant = create_tenant(session, slug="acme", name="Acme")
        user = create_user(session, tenant_id=tenant.id, email="reader@acme.test", role="security_admin")
        _key, token = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
    return app, client, token


# -- settings and slot primitives --------------------------------------------


def test_settings_defaults_and_validation() -> None:
    assert graph_build_settings({}) == (4, 60.0)
    assert graph_build_settings(
        {"GRC_LAKE_GRAPH_BUILD_CONCURRENCY": "2", "GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS": "0"}
    ) == (2, None)
    for bad in ({"GRC_LAKE_GRAPH_BUILD_CONCURRENCY": "0"}, {"GRC_LAKE_GRAPH_BUILD_CONCURRENCY": "65"}):
        with pytest.raises(ValueError):
            graph_build_settings(bad)
    for bad_timeout in ("-1", "nan", "inf", "x"):
        with pytest.raises(ValueError):
            graph_build_settings({"GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS": bad_timeout})


def test_slots_fail_fast_at_capacity_and_release() -> None:
    slots = GraphBuildSlots(2, 2)
    assert slots.try_acquire("a") is None and slots.try_acquire("a") is None
    assert slots.try_acquire("b") == "graph_build_capacity"
    assert slots.active == 2
    with pytest.raises(RuntimeError):
        slots.release("b")
    assert slots.active == 2
    slots.release("a")
    assert slots.try_acquire("b") is None
    slots.release("a")
    slots.release("b")
    assert slots.active == 0
    assert not slots._active_by_tenant
    with pytest.raises(RuntimeError):
        slots.release("a")


@pytest.mark.parametrize("capacity, expected", [(1, 1), (2, 1), (3, 1), (4, 2), (64, 32)])
def test_tenant_settings_and_constructor(capacity: int, expected: int) -> None:
    assert graph_tenant_capacity({}, capacity) == expected
    assert GraphBuildSlots(capacity).tenant_capacity == expected
    assert graph_tenant_capacity({"GRC_LAKE_GRAPH_TENANT_CONCURRENCY": str(capacity)}, capacity) == capacity
    for value in ("0", "-1", str(capacity + 1), "x", "nan", "1.5"):
        with pytest.raises(ValueError):
            graph_tenant_capacity({"GRC_LAKE_GRAPH_TENANT_CONCURRENCY": value}, capacity)
    with pytest.raises(ValueError):
        GraphBuildSlots(capacity, capacity + 1)


def test_tenant_slot_races_are_bounded_and_release_only_the_owner() -> None:
    from concurrent.futures import ThreadPoolExecutor

    slots = GraphBuildSlots(4)
    barrier = threading.Barrier(16)

    def acquire(tenant: str) -> tuple[str, str | None]:
        barrier.wait(timeout=10)
        return tenant, slots.try_acquire(tenant)

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(acquire, ["a"] * 12 + ["b"] * 4))
    admitted = [tenant for tenant, error in results if error is None]
    assert sorted(admitted) == ["a", "a", "b", "b"]
    assert slots.active == 4
    for tenant in admitted:
        slots.release(tenant)
    assert slots.active == 0 and not slots._active_by_tenant
    with pytest.raises(ValueError):
        slots.try_acquire("")


def test_build_token_deadline_and_cancel() -> None:
    now = [0.0]
    token = BuildToken(5.0, clock=lambda: now[0])
    token.check()
    now[0] = 5.0
    with pytest.raises(GraphBuildAborted) as exc:
        token.check()
    assert exc.value.reason == "deadline"
    cancelled = BuildToken(None)
    cancelled.check()
    cancelled.cancel()
    with pytest.raises(GraphBuildAborted) as exc:
        cancelled.check()
    assert exc.value.reason == "disconnected"


# -- builder checkpoints ------------------------------------------------------


def test_builder_checkpoints_inside_loops_and_aborts_without_partial_result(tmp_path: Path) -> None:
    _seed_lake(tmp_path)
    calls = 0

    def counting() -> None:
        nonlocal calls
        calls += 1

    expected = graph_module.investigation_graph(tmp_path, view="environment", depth=3, limit=100)
    observed = graph_module.investigation_graph(tmp_path, view="environment", depth=3, limit=100, checkpoint=counting)
    assert observed == expected  # a passing checkpoint never changes bindings
    assert calls > 5  # phases and per-row loops all yield to the checkpoint

    for stop_at in (1, calls // 2, calls):
        seen = 0

        def abort_at(limit: int = stop_at) -> None:
            nonlocal seen
            seen += 1
            if seen >= limit:
                raise GraphBuildAborted("deadline")

        seen = 0
        with pytest.raises(GraphBuildAborted):
            graph_module.investigation_graph(tmp_path, view="environment", depth=3, limit=100, checkpoint=abort_at)


# -- HTTP admission -----------------------------------------------------------


def _blocking_builder(monkeypatch: pytest.MonkeyPatch, started: threading.Event, release: threading.Event) -> None:
    def builder(lake: Path, **kwargs: Any) -> dict[str, Any]:
        started.set()
        assert release.wait(10)
        return {"nodes": [], "edges": []}

    monkeypatch.setattr(graph_module, "investigation_graph", builder)


def test_saturation_returns_503_with_retry_after_then_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, token = _env(tmp_path, monkeypatch, GRC_LAKE_GRAPH_BUILD_CONCURRENCY="1")
    started, release = threading.Event(), threading.Event()
    _blocking_builder(monkeypatch, started, release)
    first: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: first.update(r=client.get(URL, headers=_bearer(token))))
    worker.start()
    try:
        assert started.wait(10)
        busy = client.get(URL, headers=_bearer(token))
        assert busy.status_code == 503
        assert busy.headers["Retry-After"] == "1"
        body = busy.json()
        assert body["data"] is None
        assert body["errors"][0]["code"] == "graph_build_capacity"
        assert app.state.graph_build_slots.active == 1
    finally:
        release.set()
        worker.join(10)
    assert first["r"].status_code == 200
    assert not app.state.graph_build_slots._active_by_tenant
    assert app.state.graph_build_slots.active == 0
    assert client.get(URL, headers=_bearer(token)).status_code == 200


def test_invalid_bounds_never_take_a_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, token = _env(tmp_path, monkeypatch, GRC_LAKE_GRAPH_BUILD_CONCURRENCY="1")
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=_bearer("invalid")).status_code == 401
    assert client.get(URL, headers=_bearer(token), params={"depth": "bad"}).status_code == 400
    assert client.get(URL, headers=_bearer(token), params={"depth": 9}).status_code == 400
    assert not app.state.graph_build_slots._active_by_tenant
    assert app.state.graph_build_slots.active == 0


def test_slot_released_after_builder_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, token = _env(tmp_path, monkeypatch, GRC_LAKE_GRAPH_BUILD_CONCURRENCY="1")

    def failing(lake: Path, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(graph_module, "investigation_graph", failing)
    raising = TestClient(app, raise_server_exceptions=False)
    assert raising.get(URL, headers=_bearer(token)).status_code == 500
    assert not app.state.graph_build_slots._active_by_tenant
    assert app.state.graph_build_slots.active == 0


def test_real_builder_deadline_aborts_with_503_and_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, token = _env(tmp_path, monkeypatch, GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS="0.000001")
    response = client.get(URL, headers=_bearer(token))
    assert response.status_code == 503
    assert response.headers["Retry-After"]
    assert response.json()["errors"][0]["code"] == "graph_build_timeout"
    assert not app.state.graph_build_slots._active_by_tenant
    assert app.state.graph_build_slots.active == 0


def test_deadline_disabled_builds_normally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, token = _env(tmp_path, monkeypatch, GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS="0")
    response = client.get(URL, headers=_bearer(token), params={"view": "environment", "depth": 3, "limit": 100})
    assert response.status_code == 200
    assert response.json()["data"]["nodes"]


def test_client_disconnect_cancels_build_and_releases_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, _client, token = _env(tmp_path, monkeypatch, GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS="0")
    started = threading.Event()
    outcome: dict[str, Any] = {}

    def builder(lake: Path, *, checkpoint: Any, **kwargs: Any) -> dict[str, Any]:
        started.set()
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                checkpoint()
                time.sleep(0.01)
        except GraphBuildAborted as exc:
            outcome["reason"] = exc.reason
            raise
        outcome["reason"] = "ran to completion"
        return {"nodes": [], "edges": []}

    monkeypatch.setattr(graph_module, "investigation_graph", builder)

    async def drive() -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []
        delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            while not started.is_set():
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": URL,
            "raw_path": URL.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver"), (b"authorization", f"Bearer {token}".encode())],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        await asyncio.wait_for(app(scope, receive, send), 10)
        return sent

    sent = asyncio.run(drive())
    assert outcome["reason"] == "disconnected"
    assert not app.state.graph_build_slots._active_by_tenant
    assert app.state.graph_build_slots.active == 0
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 503
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert json.loads(body)["errors"][0]["code"] == "graph_build_cancelled"


def test_concurrent_tenants_keep_isolated_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, token = _env(tmp_path, monkeypatch, GRC_LAKE_GRAPH_BUILD_CONCURRENCY="2")
    own = client.post(
        "/api/v1/vendor-assessments",
        headers=_bearer(token),
        json={"vendor_name": "Private vendor", "template_id": "soc2-vendor-standard"},
    ).json()["data"]
    with session_scope(app.state.sessionmaker) as session:
        other = create_tenant(session, slug="other", name="Other")
        user = create_user(session, tenant_id=other.id, email="reader@other.test", role="read_only")
        _, other_token = create_api_key(session, tenant_id=other.id, user_id=user.id)
    results: dict[str, Any] = {}

    def fetch(name: str, bearer: str) -> None:
        results[name] = client.get(URL, headers=_bearer(bearer), params={"root": "vendor:" + own["id"]})

    threads = [threading.Thread(target=fetch, args=args) for args in (("own", token), ("other", other_token))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert results["own"].status_code == results["other"].status_code == 200
    assert results["own"].json()["data"]["nodes"][0]["kind"] == "vendor"
    assert results["other"].json()["data"]["root_missing"]
    assert "Private vendor" not in results["other"].text
    assert not app.state.graph_build_slots._active_by_tenant
    assert app.state.graph_build_slots.active == 0


def test_tenant_flood_cannot_take_all_slots_or_bypass_with_second_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, other_token = _env(tmp_path, monkeypatch)
    with session_scope(app.state.sessionmaker) as session:
        tenant = create_tenant(session, slug="flood", name="Flood")
        user = create_user(session, tenant_id=tenant.id, email="flood@example.test", role="read_only")
        _, token = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
        _, second_key = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
    started, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    calls = 0

    def builder(lake: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        with lock:
            calls += 1
            current = calls
            if current == 2:
                started.set()
        if current <= 2:
            assert release.wait(10)
        return {"nodes": [], "edges": []}

    monkeypatch.setattr(graph_module, "investigation_graph", builder)
    results: list[Any] = []
    workers = [
        threading.Thread(target=lambda: results.append(client.get(URL, headers=_bearer(token)))) for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    try:
        assert started.wait(10)
        # Neither credentials nor an untrusted tenant hint change the quota owner.
        busy = client.get(URL, headers={**_bearer(second_key), "X-Tenant-ID": "other"}, params={"tenant_id": "other"})
        assert busy.status_code == 503
        assert busy.json()["errors"][0]["code"] == "graph_tenant_capacity"
        assert busy.headers["Retry-After"] == "1"
        assert client.get(URL, headers=_bearer(other_token)).status_code == 200
        assert app.state.graph_build_slots.active == 2
    finally:
        release.set()
        for worker in workers:
            worker.join(10)
    assert len(results) == 2 and all(r.status_code == 200 for r in results)
    assert not app.state.graph_build_slots._active_by_tenant
    assert app.state.graph_build_slots.active == 0
    assert client.get(URL, headers=_bearer(second_key)).status_code == 200


def test_invalid_tenant_limit_stops_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRC_LAKE_GRAPH_TENANT_CONCURRENCY", "5")
    with pytest.raises(ValueError, match="GRC_LAKE_GRAPH_TENANT_CONCURRENCY"):
        create_app(tmp_path)
