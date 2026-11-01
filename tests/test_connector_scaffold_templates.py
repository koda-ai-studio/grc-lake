"""A scaffolded connector works offline on day one and fails closed against a live API."""

from __future__ import annotations

import ast
import copy
import importlib.util
import io
import json
import shutil
import sys
import time
import types
import urllib.error
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import netguard
from security_lakehouse.connector_errors import ConnectorAccessError
from security_lakehouse.connectors import validate_connector_catalog
from security_lakehouse.connectors_scaffold import scaffold_connector
from security_lakehouse.io import read_json
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.validation import validate_raw_events

ROOT = Path(__file__).resolve().parents[1]
COLLECTED = datetime(2026, 6, 3, tzinfo=UTC)
TOKEN = "acme-test-token-0f9e8d7c"  # synthetic; must never appear in evidence or errors


def _load(module_path: str, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _rest(tmp_path: Path) -> tuple[dict[str, Any], types.ModuleType]:
    result = scaffold_connector("acme-assets", title="Acme Assets", vendor="Acme", kind="rest", output_dir=tmp_path)
    return result, _load(result["module_path"], "scaffold_acme_assets")


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _http_error(url: str, code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    import email.message

    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(url, code, "error", message, io.BytesIO(b'{"error":"nope"}'))


class _FakeApi:
    def __init__(self, routes: dict[tuple[str, str | None], list[Any]]) -> None:
        self.routes = routes
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: Any, *, timeout: Any = None, label: str = "") -> _Response:
        self.requests.append(request)
        parsed = urllib.parse.urlsplit(request.full_url)
        assert parsed.scheme == "https"
        query = urllib.parse.parse_qs(parsed.query)
        queue = self.routes[(parsed.path, (query.get("cursor") or [None])[0])]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return _Response(json.dumps(item).encode())


def test_rest_scaffold_fixture_rows_reach_the_ccf_assessment_without_a_verdict(tmp_path: Path) -> None:
    result, module = _rest(tmp_path)
    fixture = Path(result["fixture_path"])
    assert fixture.is_file() and fixture.parent.name == "acme_assets"
    rows = module.collect_acme_assets_evidence(module.AcmeAssetsFixtureClient(fixture.parent), collected_at=COLLECTED)
    assert rows and validate_raw_events(rows) == []
    assert all(row["attributes"]["synthetic"] is True for row in rows)
    assert all(row["source"] == "acme_assets" for row in rows)
    # Nothing a scaffold emits may count as a pass until a human maps the vendor's fields.
    assert {row["status"] for row in rows} <= {"observed", "not_evaluated"}

    raw = tmp_path / "raw.jsonl"
    raw.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    out = tmp_path / "out"
    run_pipeline(raw, out, tenant_id="scaffold-test")
    assessment = read_json(out / "gold" / "ccf_assessment.json")
    assert assessment["safeguards"] and all(s["status"] != "pass" for s in assessment["safeguards"] if s["status"])
    assert (out / "gold" / "current_posture.json").is_file()


def test_rest_scaffold_fixture_client_treats_an_empty_export_as_a_gap(tmp_path: Path) -> None:
    result, module = _rest(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "items.json").write_text('{"items": []}', encoding="utf-8")
    rows = module.collect_acme_assets_evidence(module.AcmeAssetsFixtureClient(empty), collected_at=COLLECTED)
    assert [row["event_type"] for row in rows] == ["acme_assets.collection_gap"]
    assert rows[0]["status"] == "not_evaluated" and rows[0]["attributes"]["reason"] == "empty_collection"
    assert validate_raw_events(rows) == []


def test_rest_scaffold_live_client_pages_on_the_fixed_host_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, module = _rest(tmp_path)
    items = read_json(result["fixture_path"])["items"]
    fake = _FakeApi(
        {
            (module.ITEMS_PATH, None): [{"items": items[:1], "next": "abc"}],
            (module.ITEMS_PATH, "abc"): [{"items": items[1:], "next": None}],
        }
    )
    monkeypatch.setattr(netguard, "open_public", fake)
    client = module.AcmeAssetsClient(token=TOKEN)
    rows = module.collect_acme_assets_evidence(client, collected_at=COLLECTED)
    assert len([r for r in rows if r["event_type"] == module.EVENT_TYPE]) == len(items)
    assert [urllib.parse.urlsplit(r.full_url).netloc for r in fake.requests] == [module.API_HOST] * 2
    assert all(r.get_header("Authorization") == f"Bearer {TOKEN}" for r in fake.requests)
    assert TOKEN not in json.dumps(rows) and TOKEN not in repr(client)


def test_rest_scaffold_refuses_a_pagination_link_that_leaves_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, module = _rest(tmp_path)
    items = read_json(result["fixture_path"])["items"]
    monkeypatch.setattr(
        netguard,
        "open_public",
        _FakeApi({(module.ITEMS_PATH, None): [{"items": items, "next": "https://evil.example.net/v1/items?cursor=x"}]}),
    )
    with pytest.raises(ValueError, match="left"):
        module.collect_acme_assets_evidence(module.AcmeAssetsClient(token=TOKEN), collected_at=COLLECTED)


@pytest.mark.parametrize("code,expected", [(401, "rejected"), (403, "collection_gap")])
def test_rest_scaffold_fails_closed_on_denied_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, expected: str
) -> None:
    result, module = _rest(tmp_path)
    url = f"https://{module.API_HOST}{module.ITEMS_PATH}"
    monkeypatch.setattr(netguard, "open_public", _FakeApi({(module.ITEMS_PATH, None): [_http_error(url, code)]}))
    client = module.AcmeAssetsClient(token=TOKEN)
    if code == 401:
        with pytest.raises(ConnectorAccessError) as exc:
            module.collect_acme_assets_evidence(client, collected_at=COLLECTED)
        assert expected in str(exc.value) and TOKEN not in str(exc.value)
    else:
        rows = module.collect_acme_assets_evidence(client, collected_at=COLLECTED)
        assert [row["event_type"] for row in rows] == [f"acme_assets.{expected}"]
        assert rows[0]["status"] == "not_evaluated" and rows[0]["attributes"]["reason"] == "permission_denied"


def test_rest_scaffold_honors_retry_after_and_reports_an_exhausted_page_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, module = _rest(tmp_path)
    items = read_json(result["fixture_path"])["items"]
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    url = f"https://{module.API_HOST}{module.ITEMS_PATH}"
    monkeypatch.setattr(
        netguard,
        "open_public",
        _FakeApi(
            {
                (module.ITEMS_PATH, None): [
                    _http_error(url, 429, {"Retry-After": "3"}),
                    {"items": items, "next": "p2"},
                ],
                (module.ITEMS_PATH, "p2"): [{"items": items, "next": "p3"}],
                (module.ITEMS_PATH, "p3"): [{"items": items, "next": "p4"}],
            }
        ),
    )
    rows = module.collect_acme_assets_evidence(
        module.AcmeAssetsClient(token=TOKEN, max_pages=2), collected_at=COLLECTED
    )
    assert sleeps == [3.0]
    assert [row["event_type"] for row in rows] == ["acme_assets.collection_gap"]
    assert rows[0]["attributes"]["reason"] == "page_budget_exhausted"


def test_export_scaffold_reads_a_csv_export_through_the_pipeline(tmp_path: Path) -> None:
    result = scaffold_connector(
        "acme-hr-export", title="Acme HR export", vendor="Acme", kind="export", output_dir=tmp_path
    )
    module = _load(result["module_path"], "scaffold_acme_hr_export")
    fixture = Path(result["fixture_path"])
    assert fixture.suffix == ".csv"
    rows = module.collect_acme_hr_export_evidence(fixture.parent, collected_at=COLLECTED)
    assert rows and validate_raw_events(rows) == []
    assert {row["status"] for row in rows} <= {"observed", "not_evaluated"}
    out = tmp_path / "out"
    raw = tmp_path / "raw.jsonl"
    raw.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    run_pipeline(raw, out, tenant_id="scaffold-test")
    assert (out / "gold" / "ccf_assessment.json").is_file()
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "export.csv").write_text("id,name,status\n", encoding="utf-8")
    gap = module.collect_acme_hr_export_evidence(empty, collected_at=COLLECTED)
    assert [row["event_type"] for row in gap] == ["acme_hr_export.collection_gap"]


def test_generated_tests_are_real_and_name_the_remaining_steps(tmp_path: Path) -> None:
    result, _ = _rest(tmp_path)
    test_source = Path(result["test_path"]).read_text(encoding="utf-8")
    ast.parse(test_source)
    assert "pytest.mark.skip" not in test_source
    assert "run_pipeline" in test_source and "validate_raw_events" in test_source
    assert "TOKEN not in" in test_source
    steps = "\n".join(result["next_steps"])
    # Each step is one complete instruction, never a fragment split across list items.
    assert all(step.rstrip()[-1] in ".)" or step.startswith("Run:") for step in result["next_steps"])
    assert any(
        "docs/CONNECTORS.md" in step and "make connector-qualification-doc" in step for step in result["next_steps"]
    )
    assert "connector_runner.py" in steps and "connectors/catalog.json" in steps
    assert "connector-visuals.ts" in steps and "connector-forms.ts" in steps and "integration-presets.ts" in steps
    assert "docs/CONNECTORS.md" in steps and "make connector-qualification-doc" in steps
    entry = json.loads(Path(result["catalog_entry_path"]).read_text(encoding="utf-8"))
    assert entry["connector_id"] == "acme-assets" and entry["release_stage"] == "preview"
    assert entry["is_implemented"] is True


def test_into_tree_wires_catalog_registry_fixture_and_tests_in_place(tmp_path: Path) -> None:
    tree = tmp_path / "repo"
    for rel in (
        "connectors/catalog.json",
        "src/security_lakehouse/connector_runner.py",
        "docs/qualification/connector-evidence.json",
        "tests/test_connector_registry.py",
        "app/web/src/lib/connector-forms.ts",
        "app/web/src/lib/connector-visuals.ts",
        "app/web/src/lib/integration-presets.ts",
    ):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tree / rel)
    result = scaffold_connector("acme-assets", title="Acme Assets", vendor="Acme", kind="rest", into_tree=tree)
    assert (tree / "src/security_lakehouse/connectors_acme_assets.py").is_file()
    assert (tree / "tests/test_acme_assets_connector.py").is_file()
    assert (tree / "tests/fixtures/acme_assets/items.json").is_file()
    assert validate_connector_catalog(tree / "connectors/catalog.json") == []
    catalog = json.loads((tree / "connectors/catalog.json").read_text(encoding="utf-8"))
    ids = [row["connector_id"] for row in catalog["connectors"]]
    assert ids[-1] == "acme-assets" and len(ids) == len(set(ids))
    runner = (tree / "src/security_lakehouse/connector_runner.py").read_text(encoding="utf-8")
    ast.parse(runner)
    assert '"acme-assets": _build_acme_assets,' in runner and "def _build_acme_assets(" in runner
    assert result["into_tree"] is True
    assert len(result["wired"]) == 8
    evidence = json.loads((tree / "docs/qualification/connector-evidence.json").read_text(encoding="utf-8"))
    assert evidence["connectors"][-1] == {
        "connector_id": "acme-assets",
        "fixture_tests": ["tests/test_acme_assets_connector.py"],
        "live_record": None,
        "owner": None,
    }
    registry_test = (tree / "tests/test_connector_registry.py").read_text(encoding="utf-8")
    ast.parse(registry_test)
    assert registry_test.count('"acme-assets",') == 2
    lib = tree / "app/web/src/lib"
    assert '"acme-assets": [' in (lib / "connector-forms.ts").read_text(encoding="utf-8")
    assert '"acme-assets": {' in (lib / "connector-visuals.ts").read_text(encoding="utf-8")
    presets = (lib / "integration-presets.ts").read_text(encoding="utf-8")
    assert 'connectorId: "acme-assets"' in presets and presets.rstrip().endswith("}")
    forms = (lib / "connector-forms.ts").read_text(encoding="utf-8")
    block = forms[forms.index('"acme-assets": [') :]
    assert 'name: "credential_ref"' in block[:400] and "secret: true" not in block[:400]
    with pytest.raises(ValueError, match="already"):
        scaffold_connector("acme-assets", title="Acme Assets", vendor="Acme", kind="rest", into_tree=tree)
    with pytest.raises(ValueError, match="already"):
        scaffold_connector("snyk-vulnerabilities", vendor="x", kind="rest", into_tree=tree)


def test_scaffold_rejects_unusable_ids_and_kinds(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        scaffold_connector("***", output_dir=tmp_path)
    with pytest.raises(ValueError, match="kind"):
        scaffold_connector("acme-assets", kind="graphql", output_dir=tmp_path)  # type: ignore[arg-type]


def test_existing_cli_contract_is_preserved(tmp_path: Path) -> None:
    result = scaffold_connector("acme-audit-export", output_dir=tmp_path)
    assert copy.deepcopy(result)["registry_line"] == '    "acme-audit-export": _build_acme_audit_export,'
    assert result["catalog_flag"] == '"is_implemented": true'
    assert isinstance(result["next_steps"], list)
