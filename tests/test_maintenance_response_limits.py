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
        monkeypatch.setattr(module.urllib.request, "urlopen", opener)

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
