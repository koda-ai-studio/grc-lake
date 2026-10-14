# Vendored OSCAL JSON Schemas

`oscal_component_schema.json` and `oscal_assessment-results_schema.json` are
the NIST OSCAL v1.2.3 JSON Schema (draft-07) release artifacts for the
`component-definition` and `assessment-results` models, fetched from the
[usnistgov/OSCAL](https://github.com/usnistgov/OSCAL) `v1.2.3` GitHub release:

- <https://github.com/usnistgov/OSCAL/releases/download/v1.2.3/oscal_component_schema.json>
- <https://github.com/usnistgov/OSCAL/releases/download/v1.2.3/oscal_assessment-results_schema.json>

They are used only by `tests/test_oscal.py` to structurally validate the JSON
that `security_lakehouse.oscal` generates — never fetched at runtime. OSCAL is
published by NIST, a U.S. government agency; the schema documents are public
domain U.S. government work, same policy as the NIST catalogs referenced in
`src/security_lakehouse/framework_enrich.py`.

Re-fetch and replace both files, bump `OSCAL_VERSION` in
`src/security_lakehouse/oscal.py`, and re-run `tests/test_oscal.py` to pick up
a newer OSCAL release.

### Ambiguous CCF identities

Component-definition exports omit duplicate safeguard IDs and omit every mapping
to a repeated control ID within a safeguard, including conflicting roles or
review states. Coverage ledgers and reviewed requirement lookups use the same
projection, so an ambiguous reviewed row cannot grant coverage or export credit.
Unique sibling mappings and distinct safeguards for the same requirement remain
eligible. The raw catalog and review queue remain available for diagnosis;
`validate_safeguards` reports duplicates and assessment publication rejects them.
This defensive read behavior does not repair or approve the catalog.
