"""Maintenance downloads and storage probes must not buffer unbounded replies."""

import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from security_lakehouse import framework_enrich, framework_sync
from security_lakehouse.distributed.config import ClusterConfig
from security_lakehouse.distributed.objects import IntegrityError, ObjectStore


@pytest.mark.parametrize("module", [framework_sync, framework_enrich])
@pytest.mark.parametrize("length", [0, 16, 17])
def test_framework_download_bounds_bytes_and_closes(module, length, monkeypatch):
    monkeypatch.setattr(module, "MAX_SOURCE_BYTES", 16, raising=False)
    response = io.BytesIO(b"x" * length)
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        return response

    if module is framework_enrich:
        monkeypatch.setattr(module.netguard, "open_public", opener)

        def fetch():
            return module.fetch("https://example.gov/catalog")
    else:

        def fetch():
            return module._fetch("https://example.gov/catalog", opener=opener)

    if length > 16:
        with pytest.raises(ValueError, match="byte limit"):
            fetch()
    else:
        result = fetch()
        assert result == (
            (b"x" * length, hashlib.sha256(b"x" * length).hexdigest()) if module is framework_enrich else b"x" * length
        )
    assert response.closed
    assert calls == [1]


def test_oversized_framework_sync_preserves_source_pin_and_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(framework_sync, "MAX_SOURCE_BYTES", 16, raising=False)
    path = tmp_path / "registry.json"
    original = {
        "frameworks": [
            {
                "framework_id": "example",
                "official_source_url": "https://example.gov/catalog",
                "source_sha256": "a" * 64,
                "pulled_at": "2026-10-27",
            }
        ]
    }
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    result = framework_sync.sync_frameworks(
        path,
        fetcher=lambda url: framework_sync._fetch(url, opener=lambda *a, **kw: io.BytesIO(b"x" * 17)),
        refresh_bundle_lock=False,
    )
    assert result[0].state == "error"
    assert result[0].transient is False
    assert "byte limit" in result[0].reason
    assert path.read_bytes() == before
    assert not (tmp_path / "history.jsonl").exists()


@pytest.mark.parametrize("body", [b"first", b"first-extra", b"wrong"])
def test_object_probe_uses_bounded_read_and_cleans_up(body):
    from botocore.exceptions import ClientError

    class BoundedStream(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 6, "storage probe attempted an unbounded read"
            return super().read(size)

    stream = BoundedStream(body)
    deleted = []

    def conflict(*args, **kwargs):
        raise ClientError({"ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")

    client = SimpleNamespace(
        put_object=conflict,
        get_object=lambda **kw: {"Body": stream},
        delete_object=lambda **kw: deleted.append(kw["Key"]),
    )
    store = ObjectStore(ClusterConfig("test", "synthetic-bucket"), client=client)

    def multipart(key, path, digest):
        if path.read_bytes() == b"second":
            conflict()

    store._multipart = multipart
    if body == b"first":
        store.verify_conditional_writes()
    else:
        with pytest.raises(IntegrityError):
            store.verify_conditional_writes()
    assert stream.closed
    assert len(deleted) == 1


@pytest.mark.parametrize("module", [framework_sync, framework_enrich])
def test_framework_default_transport_uses_public_redirect_guard(module, monkeypatch):
    from security_lakehouse import netguard

    calls = []
    response = io.BytesIO(b"source")

    def guarded(request, **kwargs):
        calls.append(request.full_url)
        return response

    def unguarded(*args, **kwargs):
        pytest.fail("framework download bypassed the redirect guard")

    monkeypatch.setattr(netguard, "open_public", guarded)
    monkeypatch.setattr(module.urllib.request, "urlopen", unguarded)
    monkeypatch.setattr(module.urllib.request.OpenerDirector, "open", unguarded)
    fetch = module.fetch if module is framework_enrich else module._fetch
    fetch("https://example.gov/catalog")
    assert calls == ["https://example.gov/catalog"]
    assert response.closed


@pytest.mark.parametrize("module", [framework_sync, framework_enrich])
@pytest.mark.parametrize("case", ["private_target", "oversized_redirect"])
def test_framework_redirects_reject_private_targets_and_oversized_bodies(module, case, monkeypatch):
    from security_lakehouse import http_response
    from test_netguard import PRIVATE_IP, PUBLIC_IP, _patch_connect, _sequenced_dns

    monkeypatch.setattr(http_response, "MAX_RESPONSE_BYTES", 16)
    _sequenced_dns(
        monkeypatch,
        {"source.example": [PUBLIC_IP], "target.example": [PRIVATE_IP if case == "private_target" else PUBLIC_IP]},
    )
    body = b"x" * 17 if case == "oversized_redirect" else b""
    response = (
        b"HTTP/1.1 302 Found\r\nLocation: http://target.example/catalog\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )
    connected = _patch_connect(monkeypatch, [response])
    fetch = module.fetch if module is framework_enrich else module._fetch
    with pytest.raises(ValueError):
        fetch("http://source.example/catalog")
    assert connected == [(PUBLIC_IP, 80)]


@pytest.mark.parametrize(
    ("tool_name", "call"),
    [
        ("sync_nist_800_53", lambda tool: tool._load("low", commit="0" * 40, source_dir=None)),
        ("sync_nist_800_171r3", lambda tool: tool._fetch("analysis", None)),
    ],
)
def test_nist_sync_tools_bound_downloads(tool_name, call, monkeypatch):
    import importlib

    tool = importlib.import_module(f"tools.{tool_name}")
    monkeypatch.setattr(framework_enrich, "MAX_SOURCE_BYTES", 16)
    monkeypatch.setattr(framework_enrich.netguard, "open_public", lambda *a, **k: io.BytesIO(b"x" * 17))

    with pytest.raises(ValueError, match="byte limit"):
        call(tool)


def test_nist_800_171_xlsx_reader_refuses_oversized_members(monkeypatch):
    import zipfile

    from tools import sync_nist_800_171r3 as tool

    monkeypatch.setattr(tool, "MAX_XLSX_MEMBER_BYTES", 16)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("xl/workbook.xml", b"<" + b"x" * 64 + b"/>")
        handle.writestr("xl/_rels/workbook.xml.rels", b"<r/>")
    archive.seek(0)

    with pytest.raises(ValueError, match="xlsx member"):
        tool.read_xlsx_rows(archive)
