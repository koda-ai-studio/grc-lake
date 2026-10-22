"""Tests for the Next.js workbench wheel-packaging + serve fallback contract.

PR 1 introduces the React workbench. The Python server must:
  * detect a packaged dist (web_dist_index() returns Path) and serve from it
  * fall back to the legacy single-file dashboard when dist is empty
  * never escape the dist directory when resolving /console/* requests
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from security_lakehouse import web as web_pkg
from security_lakehouse.server import _Handler
from security_lakehouse.web import web_dist_dir


def test_dist_dir_resolves_inside_package() -> None:
    dist = web_dist_dir()
    assert dist.name == "dist"
    assert dist.parent.name == "web"


def test_dist_index_returns_none_when_unbuilt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(web_pkg, "web_dist_dir", lambda: tmp_path)
    assert web_pkg.web_dist_index() is None


def test_dist_index_returns_path_when_built(tmp_path, monkeypatch) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>react</title>", encoding="utf-8")
    monkeypatch.setattr(web_pkg, "web_dist_dir", lambda: tmp_path)
    found = web_pkg.web_dist_index()
    assert found is not None
    assert found.is_file()


def _spin_handler(lake: Path, dist: Path | None, legacy_html: bytes) -> ThreadingHTTPServer:
    console = lake / "console.html"
    console.write_bytes(legacy_html)

    class Handler(_Handler):
        lake_dir = lake
        dashboard_path = console
        web_dist = dist

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _get(server: ThreadingHTTPServer, path: str) -> tuple[int, bytes, str]:
    host, port = server.server_address
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url) as resp:  # noqa: S310 (local test url)
            return int(resp.status), resp.read(), resp.headers.get("content-type", "")
    except urllib.error.HTTPError as exc:  # pragma: no cover - debug aid
        return int(exc.code), exc.read(), exc.headers.get("content-type", "")


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    (tmp_path / "gold").mkdir()
    (tmp_path / "gold" / "control_posture.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "silver").mkdir()
    (tmp_path / "silver" / "normalized_events.jsonl").write_text("", encoding="utf-8")
    return tmp_path


def test_serve_falls_back_to_legacy_when_dist_missing(lake: Path) -> None:
    legacy = b"<!doctype html><title>legacy</title>"
    server = _spin_handler(lake, dist=None, legacy_html=legacy)
    try:
        status, body, ctype = _get(server, "/console")
        assert status == HTTPStatus.OK
        assert body == legacy
        assert ctype.startswith("text/html")
    finally:
        server.shutdown()


@pytest.mark.parametrize("entry", ["/", "/console", "/console/"])
def test_serve_opens_dashboard_when_dist_present(tmp_path: Path, lake: Path, entry: str) -> None:
    dist = tmp_path / "web_dist"
    dist.mkdir()
    react_index = b"<!doctype html><title>react</title>"
    (dist / "index.html").write_bytes(react_index)
    (dist / "dashboard").mkdir()
    (dist / "dashboard" / "index.html").write_bytes(b"<!doctype html><title>dashboard</title>")

    server = _spin_handler(lake, dist=dist, legacy_html=b"unused")
    try:
        status, body, ctype = _get(server, entry)
        assert status == HTTPStatus.OK
        assert b"<title>dashboard</title>" in body
        assert ctype.startswith("text/html")

        status, body, _ = _get(server, "/console/dashboard/")
        assert status == HTTPStatus.OK
        assert b"dashboard" in body
    finally:
        server.shutdown()


@pytest.mark.parametrize("entry", ["/", "/console", "/console/"])
def test_server_console_entries_redirect_to_dashboard(tmp_path: Path, monkeypatch, entry: str) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from security_lakehouse import server_app

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>Page not found</title>")
    monkeypatch.setattr(server_app, "web_dist_dir", lambda: dist)
    monkeypatch.setattr(server_app, "web_dist_index", lambda: dist / "index.html")
    with TestClient(server_app.create_app(tmp_path / "lake", require_auth=False)) as client:
        response = client.get(entry, follow_redirects=False)
    assert response.status_code == HTTPStatus.TEMPORARY_REDIRECT
    assert response.headers["location"] == "/console/dashboard/"


def test_dist_serving_rejects_directory_traversal(tmp_path: Path, lake: Path) -> None:
    dist = tmp_path / "web_dist"
    dist.mkdir()
    (dist / "index.html").write_bytes(b"<!doctype html>")
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"do-not-leak")

    server = _spin_handler(lake, dist=dist, legacy_html=b"legacy")
    try:
        status, body, _ = _get(server, "/console/../secret.txt")
        # urllib normalizes ../ on the client; the server still must not leak.
        assert b"do-not-leak" not in body
        assert status in {HTTPStatus.OK, HTTPStatus.NOT_FOUND}
    finally:
        server.shutdown()


def test_api_endpoints_still_respond_when_dist_present(tmp_path: Path, lake: Path) -> None:
    dist = tmp_path / "web_dist"
    dist.mkdir()
    (dist / "index.html").write_bytes(b"<!doctype html>")

    server = _spin_handler(lake, dist=dist, legacy_html=b"legacy")
    try:
        status, body, ctype = _get(server, "/api/healthz")
        assert status == HTTPStatus.OK
        assert ctype.startswith("application/json")
        assert json.loads(body)["ok"] is True
    finally:
        server.shutdown()
