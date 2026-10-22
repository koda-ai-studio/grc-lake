"""Canonical entities retain source identity and explicit assertion provenance."""

import json
from copy import deepcopy

import pytest

from security_lakehouse.cli import main
from security_lakehouse.entity_registry import build_entity_registry, entity_registry
from security_lakehouse.io import canonical_sha256, write_jsonl


def observation(source="intune", account="org-a", asset="device-1", **kwargs):
    return dict(
        source=source,
        source_account_id=account,
        tenant_id=account,
        asset_type="device",
        asset_id=asset,
        asset_name="Same Name",
        event_id=f"{source}:event",
        event_time="2026-10-21T12:00:00Z",
        raw_sha256="a" * 64,
        **kwargs,
    )


def binding(row):
    return {
        **{key: row[key] for key in ("source", "source_account_id", "asset_type", "asset_id")},
        "evidence_sha256": canonical_sha256(row),
        "asserted_by": "reviewer-1",
        "asserted_at": "2026-10-21T13:00:00Z",
        "reason": "Verified native provisioning reference",
    }


def manifest(*rows):
    return {
        "schema_version": "1.0",
        "platform_tenant_id": "customer-a",
        "entities": [{"key": "managed-device-17", "entity_type": "device", "bindings": [binding(r) for r in rows]}],
    }


def test_sources_do_not_merge_on_name_account_or_id():
    rows = [observation(), observation(source="crowdstrike"), observation(account="org-b")]
    result = build_entity_registry(rows, platform_tenant_id="customer-a")
    assert len(result["source_entities"]) == 3
    assert result["canonical_entities"] == []
    assert result["aliases"] == []
    assert len({r["id"] for r in result["source_entities"]}) == 3


def test_explicit_cross_vendor_aliases_preserve_evidence_and_replay():
    rows = [observation(), observation(source="crowdstrike")]
    result = build_entity_registry(rows, platform_tenant_id="customer-a", bindings=manifest(*rows))
    assert len(result["source_entities"]) == 2
    assert len(result["canonical_entities"]) == 1
    assert len(result["aliases"]) == 2
    for alias in result["aliases"]:
        assert alias["basis"] == "caller_asserted"
        assert alias["assertion"]["asserted_by"] == "reviewer-1"
        assert alias["assertion"]["evidence_sha256"] in {canonical_sha256(r) for r in rows}
    assert result == build_entity_registry(
        rows[::-1] + rows, platform_tenant_id="customer-a", bindings=manifest(*rows[::-1])
    )


def test_platform_tenant_changes_all_entity_ids():
    a = build_entity_registry([observation()], platform_tenant_id="customer-a")
    b = build_entity_registry([observation()], platform_tenant_id="customer-b")
    assert a["source_entities"][0]["id"] != b["source_entities"][0]["id"]


@pytest.mark.parametrize(
    "change", ["tenant", "evidence", "source", "conflict", "empty_reason", "time", "unknown_field"]
)
def test_invalid_assertions_fail_closed(change):
    rows = [observation(), observation(source="crowdstrike")]
    data = manifest(rows[0])
    record = data["entities"][0]["bindings"][0]
    if change == "tenant":
        data["platform_tenant_id"] = "other-customer"
    if change == "evidence":
        record["evidence_sha256"] = canonical_sha256(rows[1])
    if change == "source":
        record["source_account_id"] = "other-org"
    if change == "conflict":
        second = deepcopy(data["entities"][0])
        second["key"] = "different-person"
        data["entities"].append(second)
    if change == "empty_reason":
        record["reason"] = " "
    if change == "time":
        record["asserted_at"] = "not-a-date"
    if change == "unknown_field":
        record["confidence"] = 1.0
    with pytest.raises(ValueError):
        build_entity_registry(rows, platform_tenant_id="customer-a", bindings=data)


def test_source_identity_is_case_sensitive_and_type_scoped():
    rows = [observation(asset="User+A"), observation(asset="user+a"), observation(asset="User=A")]
    rows.append({**rows[0], "asset_type": "group"})
    result = build_entity_registry(rows, platform_tenant_id="customer-a")
    assert len(result["source_entities"]) == 4


@pytest.mark.parametrize("field", ["asset_id", "source", "source_account_id", "asset_type", "event_time", "raw_sha256"])
def test_missing_identity_or_provenance_is_rejected(field):
    row = observation()
    row[field] = ""
    with pytest.raises(ValueError):
        build_entity_registry([row], platform_tenant_id="customer-a")


def test_observation_bounds_do_not_imply_lifecycle():
    rows = [observation(), {**observation(), "event_time": "2026-10-20T12:00:00Z"}]
    entity = build_entity_registry(rows, platform_tenant_id="customer-a")["source_entities"][0]
    assert entity["first_observed_at"] == "2026-10-20T12:00:00Z"
    assert entity["last_observed_at"] == "2026-10-21T12:00:00Z"
    assert "status" not in entity
    assert len(entity["observations"]) == 2


def test_cli_exports_inspectable_registry_without_modifying_lake(tmp_path, capsys):
    lake = tmp_path / "lake"
    rows = [observation(), observation(source="crowdstrike")]
    write_jsonl(lake / "silver/normalized_events.jsonl", rows)
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(manifest(*rows)))
    before = (lake / "silver/normalized_events.jsonl").read_bytes()
    assert main(["entities", "export", "--lake", str(lake), "--tenant-id", "customer-a", "--bindings", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["aliases"]) == 2
    assert result == entity_registry(lake, platform_tenant_id="customer-a", bindings=manifest(*rows))
    assert (lake / "silver/normalized_events.jsonl").read_bytes() == before


def test_observation_limit_is_enforced():
    with pytest.raises(ValueError, match="limit"):
        build_entity_registry([observation(), observation()], platform_tenant_id="customer-a", max_observations=1)


def test_fractional_observation_time_bounds_are_chronological():
    rows = [observation(), {**observation(), "event_time": "2026-10-21T12:00:00.1Z"}]
    entity = build_entity_registry(rows, platform_tenant_id="customer-a")["source_entities"][0]
    assert entity["first_observed_at"] == "2026-10-21T12:00:00Z"
    assert entity["last_observed_at"] == "2026-10-21T12:00:00.100000Z"


def test_pinned_generation_and_public_schemas(tmp_path, monkeypatch):
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    from security_lakehouse import entity_registry as module
    from security_lakehouse.generations import generation_identity
    from security_lakehouse.io import read_jsonl
    from security_lakehouse.pipeline import run_pipeline

    root = Path(__file__).resolve().parents[1]
    lake = tmp_path / "lake"
    raw = root / "data/raw/security_events.jsonl"
    run_pipeline(raw, lake)
    first = generation_identity(lake)
    rows = read_jsonl(lake / "silver/normalized_events.jsonl")
    claims = manifest(rows[0])
    original = module.build_entity_registry

    def concurrent_publish(events, **kwargs):
        result = original(events, **kwargs)
        subset = tmp_path / "subset.jsonl"
        write_jsonl(subset, read_jsonl(raw)[:1])
        run_pipeline(subset, lake)
        return result

    monkeypatch.setattr(module, "build_entity_registry", concurrent_publish)
    result = entity_registry(lake, platform_tenant_id="customer-a", bindings=claims)
    assert result["generation"] == first
    assert generation_identity(lake) != first
    assert sum(len(e["observations"]) for e in result["source_entities"]) == len(rows)
    for name, value in [("entity-bindings", claims), ("entity-registry", result)]:
        schema = json.loads((root / f"data/schemas/{name}.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    payload = {k: v for k, v in result.items() if k not in {"content_sha256", "generation"}}
    assert result["content_sha256"] == canonical_sha256(payload)


def test_rebinding_changes_claim_hash_without_changing_source_identity():
    row = observation()
    before = build_entity_registry([row], platform_tenant_id="customer-a", bindings=manifest(row))
    claims = manifest(row)
    claims["entities"][0]["key"] = "different-device"
    after = build_entity_registry([row], platform_tenant_id="customer-a", bindings=claims)
    assert before["source_entities"] == after["source_entities"]
    assert before["aliases"] != after["aliases"]
    assert before["content_sha256"] != after["content_sha256"]


def test_invalid_cli_claim_emits_no_partial_registry(tmp_path, capsys):
    lake = tmp_path / "lake"
    row = observation()
    write_jsonl(lake / "silver/normalized_events.jsonl", [row])
    claims = manifest(row)
    claims["platform_tenant_id"] = "other"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(claims))
    assert main(["entities", "export", "--lake", str(lake), "--tenant-id", "customer-a", "--bindings", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "tenant mismatch" in captured.err


def test_local_export_rejected_in_distributed_mode(tmp_path, monkeypatch, capsys):
    from security_lakehouse.distributed.config import ClusterConfig

    monkeypatch.setattr(ClusterConfig, "from_env", classmethod(lambda cls: cls("cluster", "bucket")))
    assert main(["entities", "export", "--lake", str(tmp_path), "--tenant-id", "customer-a"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "local lake commands require local mode" in captured.err


def test_missing_evidence_file_does_not_become_empty_inventory(tmp_path):
    with pytest.raises(FileNotFoundError):
        entity_registry(tmp_path, platform_tenant_id="customer-a")


def test_duplicate_alias_is_idempotent_and_canonical_id_survives_new_observations():
    row = observation()
    claims = manifest(row)
    initial = build_entity_registry([row], platform_tenant_id="customer-a", bindings=claims)
    claims["entities"][0]["bindings"].append(deepcopy(claims["entities"][0]["bindings"][0]))
    replay = build_entity_registry([row], platform_tenant_id="customer-a", bindings=claims)
    assert replay == initial
    later = {**row, "event_time": "2026-10-22T12:00:00Z"}
    updated = build_entity_registry([row, later], platform_tenant_id="customer-a", bindings=claims)
    assert updated["source_entities"][0]["id"] == initial["source_entities"][0]["id"]
    assert updated["canonical_entities"] == initial["canonical_entities"]
    assert updated["content_sha256"] != initial["content_sha256"]
