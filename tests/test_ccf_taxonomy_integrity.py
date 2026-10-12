"""Taxonomy joins must never silently discard or coerce identities."""

import json

import pytest

from security_lakehouse.safeguards import load_ccf_categories, load_ccf_families, validate_ccf_taxonomy


def _taxonomy():
    return {
        "categories": [{"category_id": "security"}],
        "families": [{"family_id": "access", "category": "security"}],
    }


def test_duplicate_family_identity_is_reported():
    payload = _taxonomy()
    payload["families"].append(dict(payload["families"][0]))
    assert any("duplicate family" in error for error in validate_ccf_taxonomy(payload))


@pytest.mark.parametrize("field", ["family_id", "category"])
@pytest.mark.parametrize("value", [None, "", "   ", 12, [], {}])
def test_family_join_keys_must_be_nonempty_strings(field, value):
    payload = _taxonomy()
    payload["families"][0][field] = value
    assert validate_ccf_taxonomy(payload)


@pytest.mark.parametrize("value", [None, "", "   ", 12, [], {}])
def test_category_identity_must_be_a_nonempty_string(value):
    payload = _taxonomy()
    payload["categories"][0]["category_id"] = value
    payload["families"][0]["category"] = value
    assert validate_ccf_taxonomy(payload)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"categories": None, "families": []},
        {"categories": [], "families": {}},
        {"categories": [None], "families": [None]},
    ],
)
def test_malformed_taxonomy_returns_diagnostics(payload):
    assert validate_ccf_taxonomy(payload)


@pytest.mark.parametrize("loader", [load_ccf_families, load_ccf_categories])
def test_loaders_reject_ambiguous_taxonomy(tmp_path, loader):
    payload = _taxonomy()
    payload["families"].append(dict(payload["families"][0]))
    path = tmp_path / "families.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="duplicate family"):
        loader(path)


def test_safeguard_validation_reports_taxonomy_errors(tmp_path, monkeypatch):
    from security_lakehouse import safeguards

    payload = _taxonomy()
    payload["families"].append(dict(payload["families"][0]))
    path = tmp_path / "families.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(safeguards, "DEFAULT_FAMILIES", path)
    errors = safeguards.validate_safeguards({"schema": safeguards.SCHEMA, "safeguards": []})
    assert any("duplicate family" in error for error in errors)
