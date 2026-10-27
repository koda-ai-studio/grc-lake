"""Source extraction keeps parameter cardinality and rejects unverified input."""

import pytest
from tools.sync_nist53_assessment_safeguards import build_entries, flatten, resolve, source_controls


def test_all_catalogued_nist_obligations_have_source_assessment_contracts():
    import json
    from pathlib import Path

    from security_lakehouse.catalog import load_control_catalog

    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / "controls/nist53_assessment_expansion.json").read_text())
    expected = {
        cid.removeprefix("NIST-800-53-")
        for cid, control in load_control_catalog().items()
        if control["framework_id"] == "nist-800-53-rev5"
    }
    assert set(plan["control_ids"]) == expected
    assert len(plan["control_ids"]) == len(expected) == 1014


@pytest.mark.parametrize("risk_domain", [None, "identity"])
def test_expansion_preserves_exact_reviewed_contracts_and_rejects_changed_or_removed_ones(risk_domain):
    from copy import deepcopy

    from tools.sync_nist53_assessment_safeguards import reconcile_entries

    proposed = {
        "safeguard_id": "SG-NIST53-AC-1",
        "objective": "Assess the full source obligation.",
        "satisfies": [{"control_id": "NIST-800-53-AC-1", "review_status": "proposed"}],
    }
    if risk_domain is not None:
        proposed["risk_domain"] = risk_domain
    reviewed = deepcopy(proposed)
    reviewed["satisfies"][0].update(review_status="reviewed", reviewed_by="reviewer", maintainer_review_ref="receipt")
    new = {**deepcopy(proposed), "safeguard_id": "SG-NIST53-AC-2"}
    assert reconcile_entries([reviewed], [proposed, new]) == [reviewed, new]
    assert reconcile_entries(reconcile_entries([reviewed], [proposed, new]), [proposed, new]) == [reviewed, new]
    assert reviewed["satisfies"][0]["review_status"] == "reviewed"
    with pytest.raises(ValueError, match="reviewed contract"):
        reconcile_entries([reviewed], [{**proposed, "objective": "Weaker requirement."}])
    with pytest.raises(ValueError, match="reviewed contract"):
        reconcile_entries([reviewed], [])


def test_expansion_rejects_duplicate_targets_instead_of_overwriting_them():
    from tools.sync_nist53_assessment_safeguards import reconcile_entries

    entry = {"safeguard_id": "SG-NIST53-AC-1", "satisfies": [{"review_status": "proposed"}]}
    with pytest.raises(ValueError, match="duplicate"):
        reconcile_entries([entry, entry], [entry])
    with pytest.raises(ValueError, match="duplicate"):
        reconcile_entries([entry], [entry, entry])


def test_new_contracts_do_not_inherit_prior_batch_approval():
    import json
    from pathlib import Path

    from security_lakehouse.safeguards import load_safeguards

    root = Path(__file__).resolve().parents[1]
    receipt = json.loads((root / "controls/reviews/2026-10-14-source-batches.json").read_text())
    approved = {r["safeguard_id"] for r in receipt["mappings"] if r["safeguard_id"].startswith("SG-NIST53-")}
    new = [
        entry
        for entry in load_safeguards()["safeguards"]
        if entry["safeguard_id"].startswith("SG-NIST53-") and entry["safeguard_id"] not in approved
    ]
    assert len(approved) == 381
    assert len(new) == 633
    for entry in new:
        member = entry["satisfies"][0]
        assert member["review_status"] == "proposed"
        assert not any(member.get(field) for field in ("maintainer_review_ref", "reviewed_by", "reviewed_at"))


def test_parameter_choices_keep_the_source_cardinality_and_identifier():
    params = {"p": {"id": "p", "select": {"how-many": "one-or-more", "choice": ["people", "services"]}}}
    assert resolve("Apply to {{ insert: param, p }}.", params) == (
        "Apply to [organization-defined p: select one-or-more from: people; services]."
    )


def test_unknown_or_recursive_parameter_is_not_silently_dropped():
    with pytest.raises(ValueError, match="unresolved source parameter"):
        resolve("{{ insert: param, missing }}", {})
    with pytest.raises(ValueError, match="cyclic"):
        resolve("{{ insert: param, p }}", {"p": {"label": "{{ insert: param, p }}"}})


def test_nested_clauses_retain_parent_conditions_and_order():
    assert flatten(
        [{"prose": "When applicable:", "parts": [{"prose": "First condition."}, {"prose": "Second condition."}]}]
    ) == ["When applicable:", "First condition.", "Second condition."]


def test_catalog_bytes_must_match_the_manifest_before_any_mapping_is_built():
    with pytest.raises(ValueError, match="SHA-256"):
        build_entries(b"{}", {"source": {"catalog_sha256": "0" * 64}}, {})


def test_complete_scope_cannot_silently_omit_an_active_source_control():
    import hashlib
    import json

    raw = json.dumps(
        {"catalog": {"metadata": {"version": "test"}, "groups": [{"controls": [{"id": "ac-1"}]}]}}
    ).encode()
    plan = {
        "source": {
            "catalog_sha256": hashlib.sha256(raw).hexdigest(),
            "version": "test",
            "oscal_commit": "test",
            "catalog_file": "test.json",
        },
        "coverage_scope": "all_active_controls",
        "control_ids": [],
    }
    with pytest.raises(ValueError, match="active source controls"):
        build_entries(raw, plan, {})


def test_duplicate_source_controls_and_conflicting_parameters_are_rejected():
    with pytest.raises(ValueError, match="duplicate source control"):
        source_controls({"catalog": {"groups": [{"controls": [{"id": "ac-1"}, {"id": "ac-1"}]}]}})
    with pytest.raises(ValueError, match="conflicting source parameter"):
        source_controls(
            {
                "catalog": {
                    "groups": [
                        {
                            "controls": [
                                {"id": "ac-1", "params": [{"id": "p", "label": "first"}]},
                                {"id": "ac-2", "params": [{"id": "p", "label": "second"}]},
                            ]
                        }
                    ]
                }
            }
        )


def test_manifest_cannot_move_an_obligation_into_an_unrelated_ccf_family():
    import hashlib
    import json

    source = {
        "catalog": {
            "metadata": {"version": "test"},
            "groups": [
                {
                    "controls": [
                        {
                            "id": "ac-2",
                            "title": "Accounts",
                            "parts": [
                                {"name": "statement", "prose": "Manage accounts."},
                                {"name": "assessment-objective", "prose": "Accounts are managed."},
                                {
                                    "name": "assessment-method",
                                    "props": [{"name": "method", "value": "EXAMINE"}],
                                    "parts": [{"prose": "Account records."}],
                                },
                            ],
                        }
                    ]
                }
            ],
        }
    }
    raw = json.dumps(source).encode()
    plan = {
        "source": {
            "catalog_sha256": hashlib.sha256(raw).hexdigest(),
            "version": "test",
            "oscal_commit": "test",
            "catalog_file": "test.json",
            "name": "Synthetic source",
        },
        "control_ids": ["AC-2"],
        "families": {"AC": "privacy"},
    }
    catalog = {"NIST-800-53-AC-2": {"framework_id": "nist-800-53-rev5", "version": "test", "asset_types": ["account"]}}
    with pytest.raises(ValueError, match="source family"):
        build_entries(raw, plan, catalog)
