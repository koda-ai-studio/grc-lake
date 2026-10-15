"""Source extraction keeps parameter cardinality and rejects unverified input."""

import pytest
from tools.sync_nist53_assessment_safeguards import build_entries, flatten, resolve, source_controls


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
