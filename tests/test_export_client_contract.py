"""Both export protocols preserve query bounds and reject cursor cycles."""

from urllib.parse import parse_qs, urlsplit

import pytest

from security_lakehouse.connectors_runtime import RuntimeGatewayClient
from security_lakehouse.connectors_siem import SiemClient
from security_lakehouse.ingestion.paginate import IncompleteCollectionError


@pytest.mark.parametrize("client_type,method", [(SiemClient, "alerts"), (RuntimeGatewayClient, "events")])
def test_export_cursor_cycle_is_incomplete_and_keeps_since(client_type, method, monkeypatch):
    client = client_type("https://export.example", token="test-token")
    seen = []

    def fetch(url):
        seen.append(parse_qs(urlsplit(url).query))
        return {"items": [{"id": "one"}], "next_cursor": "private-cursor"}

    monkeypatch.setattr(client, "_fetch_json", fetch)
    with pytest.raises(IncompleteCollectionError) as failure:
        getattr(client, method)(since="2026-10-01T00:00:00Z")
    assert len(seen) == 2
    assert all(query["since"] == ["2026-10-01T00:00:00Z"] for query in seen)
    assert failure.value.pages_fetched == 2
    assert "private-cursor" not in str(failure.value)
