"""Shared pytest configuration."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Signed session cookies are mandatory whenever server auth is enabled.
os.environ.setdefault("GRC_LAKE_COOKIE_SIGNING_KEY", "test-cookie-signing-key-for-pytest-only")

_ENTRY_POINT_FIXTURE_MODULES = frozenset(
    path.stem for path in (Path(__file__).parent / "fixtures" / "entry_point_connectors").glob("*.py")
)


@pytest.fixture(autouse=True)
def _isolate_connector_registry():
    """Restore process-global connector state after every test.

    ``connector_runner.REGISTRY`` is a module-level dict, and the entry-point
    fixture connectors stay importable from ``sys.modules`` after their
    ``sys.path`` entry is removed. Either would let one test's connectors leak
    into a later test's registry or catalog view.
    """
    runner = sys.modules.get("security_lakehouse.connector_runner")
    snapshot = dict(runner.REGISTRY) if runner is not None else None
    try:
        yield
    finally:
        if runner is not None and snapshot is not None and snapshot != runner.REGISTRY:
            runner.REGISTRY.clear()
            runner.REGISTRY.update(snapshot)
        for name in _ENTRY_POINT_FIXTURE_MODULES & sys.modules.keys():
            del sys.modules[name]


# Minimal Iceberg REST catalog on loopback for REST client hardening tests.
@pytest.fixture
def rest_stub():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {"headers": [], "overrides": {}, "redirect": False, "expired": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["headers"].append(self.headers.get("Authorization"))
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()
                return
            if state["expired"] and "/config" not in self.path:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"expired","type":"UnauthorizedException","code":401}}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = (
                {"defaults": {}, "overrides": state["overrides"]} if "/config" in self.path else {"namespaces": []}
            )
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def catalog():
    from distributed_fixtures import _create_distributed_catalog

    yield from _create_distributed_catalog()


@pytest.fixture
def replicas(catalog, tmp_path, monkeypatch):
    from distributed_fixtures import _create_distributed_replicas

    yield from _create_distributed_replicas(catalog, tmp_path, monkeypatch)


@pytest.fixture
def proposed_source_catalog(tmp_path_factory, monkeypatch):
    """Exercise proposal-to-review behavior independently of later maintainer decisions.

    Only the explicitly receipted batch decisions are rolled back in this temporary
    catalog. The shipped catalog and live receipt/coverage tests remain untouched.
    """
    from security_lakehouse import safeguards

    payload = json.loads(safeguards.DEFAULT_SAFEGUARDS.read_text())
    for entry in payload["safeguards"]:
        for member in entry["satisfies"]:
            if member.get("maintainer_review_ref") in {
                "controls/reviews/2026-10-14-source-batches.json",
                "controls/reviews/2026-10-15-soc2-iso-repairs.json",
            }:
                member["review_status"] = "proposed"
                for key in ("maintainer_review_ref", "reviewed_by", "reviewed_at"):
                    member.pop(key)
    path = tmp_path_factory.mktemp("proposal-catalog") / "safeguards.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(safeguards, "DEFAULT_SAFEGUARDS", path)
