"""Append-only canonical binding history, concurrency, and historical provenance."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from security_lakehouse.entity_history import binding_history, record_bindings, stored_entity_registry
from security_lakehouse.io import canonical_sha256, write_jsonl


@pytest.fixture
def evidence(tmp_path):
    lake = tmp_path / "lake"
    row = dict(
        source="intune",
        source_account_id="org-a",
        tenant_id="org-a",
        asset_type="device",
        asset_id="device-1",
        event_id="evt-1",
        event_time="2026-10-21T12:00:00Z",
        raw_sha256="a" * 64,
    )
    write_jsonl(lake / "silver/normalized_events.jsonl", [row])
    binding = {k: row[k] for k in ("source", "source_account_id", "asset_type", "asset_id")}
    binding.update(
        evidence_sha256=canonical_sha256(row),
        asserted_by="reviewer",
        asserted_at="2026-10-21T13:00:00Z",
        reason="Verified enrollment reference",
    )
    manifest = {
        "schema_version": "1.0",
        "platform_tenant_id": "customer-a",
        "entities": [{"key": "device-17", "entity_type": "device", "bindings": [binding]}],
    }
    return lake, row, manifest


def record(lake, manifest, revision=0, request="request-1", **kwargs):
    return record_bindings(
        lake,
        platform_tenant_id="customer-a",
        bindings=manifest,
        actor="operator",
        reason="Record reviewed source references",
        expected_revision=revision,
        request_id=request,
        **kwargs,
    )


def test_record_rebind_revoke_preserves_prior_evidence(evidence):
    lake, row, manifest = evidence
    one = record(lake, manifest)
    changed = deepcopy(manifest)
    changed["entities"][0]["key"] = "device-18"
    two = record(lake, changed, 1, "request-2")
    three = record(lake, {**manifest, "entities": []}, 2, "request-3")
    assert [one["revision"], two["revision"], three["revision"]] == [1, 2, 3]
    history = binding_history(lake, platform_tenant_id="customer-a")
    assert history["tip_hash"] == three["record_hash"]
    assert len(history["revisions"]) == 3
    assert len(two["changes"]["changed"]) == 1
    assert len(three["changes"]["removed"]) == 1
    assert stored_entity_registry(lake, platform_tenant_id="customer-a")["aliases"] == []
    historical = stored_entity_registry(lake, platform_tenant_id="customer-a", revision=1)
    assert historical["canonical_entities"][0]["key"] == "device-17"
    assert historical["source_entities"][0]["observations"][0]["evidence_sha256"] == canonical_sha256(row)


def test_retry_is_exactly_once_even_after_evidence_disappears(evidence):
    lake, _, manifest = evidence
    first = record(lake, manifest)
    (lake / "silver/normalized_events.jsonl").unlink()
    assert record(lake, manifest) == first
    assert len(binding_history(lake, platform_tenant_id="customer-a")["revisions"]) == 1
    assert stored_entity_registry(lake, platform_tenant_id="customer-a", revision=1)["aliases"]
    with pytest.raises(FileNotFoundError):
        stored_entity_registry(lake, platform_tenant_id="customer-a")


def test_stale_revision_and_reused_request_with_different_payload_fail(evidence):
    lake, _, manifest = evidence
    record(lake, manifest)
    changed = {**manifest, "entities": []}
    with pytest.raises(ValueError, match="request"):
        record(lake, changed)
    with pytest.raises(ValueError, match="revision"):
        record(lake, changed, 0, "new-request")
    assert len(binding_history(lake, platform_tenant_id="customer-a")["revisions"]) == 1


def test_two_concurrent_writers_cannot_overwrite_each_other(evidence):
    lake, _, manifest = evidence

    def attempt(request):
        try:
            return record(lake, manifest, request=request)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["one", "two"]))
    assert sum(result is not None for result in results) == 1
    assert len(binding_history(lake, platform_tenant_id="customer-a")["revisions"]) == 1


def test_history_cannot_be_read_or_changed_in_another_tenant(evidence):
    lake, _, manifest = evidence
    record(lake, manifest)
    with pytest.raises(ValueError, match="tenant"):
        binding_history(lake, platform_tenant_id="other")
    with pytest.raises(ValueError, match="tenant"):
        record_bindings(
            lake,
            platform_tenant_id="other",
            bindings={**manifest, "platform_tenant_id": "other"},
            actor="operator",
            reason="test",
            expected_revision=1,
            request_id="other",
        )


@pytest.mark.parametrize("corruption", ["alter", "torn", "reorder"])
def test_corrupt_history_fails_before_read_or_append(evidence, corruption):
    lake, _, manifest = evidence
    record(lake, manifest)
    record(lake, manifest, 1, "second")
    path = lake / "entities/bindings.jsonl"
    lines = path.read_text().splitlines()
    if corruption == "alter":
        data = json.loads(lines[0])
        data["reason"] = "rewritten"
        lines[0] = json.dumps(data)
    elif corruption == "torn":
        lines[-1] = lines[-1][:30]
    else:
        lines.reverse()
    path.write_text("\n".join(lines) + "\n")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        binding_history(lake, platform_tenant_id="customer-a")
    with pytest.raises(ValueError):
        record(lake, manifest, 2, "third")
    assert path.read_bytes() == before


def test_invalid_evidence_does_not_append_a_revision(evidence):
    lake, _, manifest = evidence
    record(lake, manifest)
    changed = deepcopy(manifest)
    changed["entities"][0]["bindings"][0]["evidence_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="evidence"):
        record(lake, changed, 1, "invalid")
    assert len(binding_history(lake, platform_tenant_id="customer-a")["revisions"]) == 1


def test_canonical_key_cannot_change_type_after_revocation(evidence):
    lake, _, manifest = evidence
    record(lake, manifest)
    record(lake, {**manifest, "entities": []}, 1, "revoke")
    changed = deepcopy(manifest)
    changed["entities"][0]["entity_type"] = "person"
    with pytest.raises(ValueError, match="type"):
        record(lake, changed, 2, "retype")


def test_symlinked_history_directory_is_rejected(evidence, tmp_path):
    lake, _, manifest = evidence
    outside = tmp_path / "outside"
    outside.mkdir()
    (lake / "entities").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        record(lake, manifest)
    assert list(outside.iterdir()) == []


def test_revocation_still_works_after_source_file_is_removed(evidence):
    lake, _, manifest = evidence
    record(lake, manifest)
    (lake / "silver/normalized_events.jsonl").unlink()
    result = record(lake, {**manifest, "entities": []}, 1, "revoke")
    assert len(result["changes"]["removed"]) == 1
    assert stored_entity_registry(lake, platform_tenant_id="customer-a", revision=2)["aliases"] == []


def test_history_size_limit_rejects_write_without_changing_file(evidence, monkeypatch):
    from security_lakehouse import entity_history

    lake, _, manifest = evidence
    record(lake, manifest)
    path = lake / "entities/bindings.jsonl"
    before = path.read_bytes()
    monkeypatch.setattr(entity_history, "MAX_HISTORY_BYTES", len(before) + 1)
    with pytest.raises(ValueError, match="byte limit"):
        record(lake, manifest, 1, "second")
    assert path.read_bytes() == before


def test_record_keeps_only_referenced_observations(evidence):
    lake, row, manifest = evidence
    unbound = {**row, "asset_id": "unbound-device", "event_id": "unbound-event"}
    write_jsonl(lake / "silver/normalized_events.jsonl", [row, unbound])
    record(lake, manifest)
    stored = json.loads((lake / "entities/bindings.jsonl").read_text())
    assert stored["evidence"] == [row]
    assert len(stored_entity_registry(lake, platform_tenant_id="customer-a")["source_entities"]) == 2
    assert len(stored_entity_registry(lake, platform_tenant_id="customer-a", revision=1)["source_entities"]) == 1


def test_cli_and_persisted_json_contracts(evidence, tmp_path, capsys):
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    from security_lakehouse.cli import main

    lake, _, manifest = evidence
    source = tmp_path / "bindings.json"
    source.write_text(json.dumps(manifest))
    assert (
        main(
            [
                "entities",
                "record",
                "--lake",
                str(lake),
                "--tenant-id",
                "customer-a",
                "--bindings",
                str(source),
                "--actor",
                "operator",
                "--reason",
                "reviewed references",
                "--expected-revision",
                "0",
                "--request-id",
                "cli-first",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["revision"] == 1
    assert (
        main(
            [
                "entities",
                "export",
                "--lake",
                str(lake),
                "--tenant-id",
                "customer-a",
                "--stored-bindings",
                "--revision",
                "1",
            ]
        )
        == 0
    )
    export = json.loads(capsys.readouterr().out)
    assert export["binding_history"]["mode"] == "recorded_binding_evidence"
    assert main(["entities", "history", "--lake", str(lake), "--tenant-id", "customer-a"]) == 0
    assert len(json.loads(capsys.readouterr().out)["revisions"]) == 1
    root = Path(__file__).resolve().parents[1] / "data/schemas"
    binding_schema = json.loads((root / "entity-bindings.schema.json").read_text())
    registry = Registry().with_resource("entity-bindings.schema.json", Resource.from_contents(binding_schema))
    stored = json.loads((lake / "entities/bindings.jsonl").read_text())
    for name, value in (("entity-binding-revision", stored), ("entity-registry", export)):
        schema = json.loads((root / f"{name}.schema.json").read_text())
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(value)
    payload = {k: v for k, v in export.items() if k not in {"content_sha256", "generation", "binding_history"}}
    assert export["content_sha256"] == canonical_sha256(payload)


def test_retry_recovers_a_durable_append_with_lost_response(evidence, monkeypatch):
    from security_lakehouse import ledger

    lake, _, manifest = evidence
    original = ledger._append_once

    def lost_response(path, data):
        original(path, data)
        raise OSError("simulated lost response after durable append")

    monkeypatch.setattr(ledger, "_append_once", lost_response)
    with pytest.raises(OSError):
        record(lake, manifest)
    receipt = record(lake, manifest)
    assert receipt["revision"] == 1
    assert len(binding_history(lake, platform_tenant_id="customer-a")["revisions"]) == 1


def test_recording_uses_one_generation_and_survives_publication(evidence, tmp_path, monkeypatch):
    from pathlib import Path

    from security_lakehouse import entity_history
    from security_lakehouse.generations import generation_identity
    from security_lakehouse.io import read_jsonl
    from security_lakehouse.pipeline import run_pipeline

    lake, _, manifest = evidence
    raw = Path(__file__).resolve().parents[1] / "data/raw/security_events.jsonl"
    run_pipeline(raw, lake)
    first = generation_identity(lake)
    row = read_jsonl(lake / "silver/normalized_events.jsonl")[0]
    assertion = manifest["entities"][0]["bindings"][0]
    assertion.update({key: row[key] for key in ("source", "source_account_id", "asset_type", "asset_id")})
    assertion["evidence_sha256"] = canonical_sha256(row)
    original = entity_history.entity_registry

    def switch_after_validation(*args, **kwargs):
        result = original(*args, **kwargs)
        subset = tmp_path / "subset.jsonl"
        write_jsonl(subset, read_jsonl(raw)[-1:])
        run_pipeline(subset, lake)
        return result

    monkeypatch.setattr(entity_history, "entity_registry", switch_after_validation)
    receipt = record(lake, manifest)
    assert receipt["generation"] == first
    assert generation_identity(lake) != first
    old = stored_entity_registry(lake, platform_tenant_id="customer-a", revision=1)
    assert old["generation"] == first
    assert old["aliases"][0]["assertion"]["evidence_sha256"] == canonical_sha256(row)
    monkeypatch.setattr(entity_history, "entity_registry", original)
    with pytest.raises(ValueError, match="evidence"):
        stored_entity_registry(lake, platform_tenant_id="customer-a")
