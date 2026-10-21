# Portable framework coverage report

Export the frozen CCF requirement results, mapping-review gaps, and evidence
blockers from one assessment as an offline HTML/JSON ZIP. This current-source
CLI gives a reviewer the complete selected catalog denominator, including
requirements with no observed evidence. It does not approve mappings, create
evidence requests, or change control verdicts.

## Export

Use an evaluated lake and its assessment tenant ID:

```bash
grc-lake assessment framework-report \
  --lake ./lake --tenant-id example-company \
  --framework soc2 \
  --framework iso-27001-2022 \
  --framework iso-27001-isms-2022 \
  --framework nist-csf-2.0 \
  --framework nist-800-53-rev5 \
  --out ./framework-coverage.zip
```

Omit `--framework` to include every framework in the frozen assessment. The ISO
Annex A and ISMS management-clause packs have separate IDs and rows. Unknown IDs
fail rather than silently disappearing. The denominator is GRC Lake's frozen,
authored catalog; it is not a claim of complete normative standards coverage.
See [release readiness](RELEASE_READINESS.md) for published-package availability.

Unzip the archive into a private directory and open `index.html`. It uses no
scripts, network requests, fonts, or external resources. Expand a framework to
review its requirements and next actions; expand sections before printing.
`coverage.json` carries the same results for another tool. `manifest.json`
records file hashes and the source generation identity.

## Read the columns

| Column                | Meaning                                                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Catalogued            | Every requirement in the selected frozen catalog, whether observed or not                                                            |
| Mapped                | Requirements with at least one non-rejected implementation mapping; includes proposals                                               |
| With reviewed mapping | Requirements with at least one recorded reviewed implementation mapping; pending additional mappings can still block the requirement |
| Assessed / catalogued | Stored CCF requirement results of `pass` or `fail`, divided by the full catalogued count                                             |
| Pass / Fail           | Counts of the stored CCF requirement verdicts, without recalculation                                                                 |
| With gaps             | Requirements with one or more recorded mapping or evidence blockers                                                                  |

`stale`, `not_evaluated`, and `unmapped` remain in the denominator and are listed
separately in JSON `status_counts`. A stale observation is not counted as a
current assessed result. Two mappings to one requirement count as one mapped
requirement. Context-only mappings do not establish implementation coverage.

The report uses the same [requirement-gap explanations](CCF_REQUIREMENT_GAPS.md)
as the API and console, including blocking safeguards, unassessed observed
assets, invalid bindings, and pending mapping review. It does not invent missing
evidence types or infer unobserved provider assets. Follow the listed actions in
the relevant mapping-review or safeguard workflow, then publish a new assessment.

These are CCF requirement results; direct control-posture rows can differ.
Cataloguing, reviewing a mapping, assessing observed evidence, and establishing
population completeness are separate facts. A pass with no retained gaps is not
certification, an auditor opinion, or proof of operating effectiveness across an
entire company.

## Provenance and integrity

The exporter pins one sealed generation for the whole read and verifies its
artifact hashes before using the frozen catalog and SQLite CCF summary. A new
assessment published during export cannot mix new results with old metadata.
`--generation-id <id>` rejects a changed current generation; it does not select a
historical generation. Missing, legacy-without-projection, corrupted, or
catalog-inconsistent assessment detail fails closed.

`--tenant-id` must match the frozen assessment tenant. This is a local CLI scope
check, not a substitute for filesystem authorization. The report excludes raw
evidence, per-asset arrays, source paths, and credentials. It still contains
control gaps and the tenant identifier, so share it only with intended reviewers.

Explicit synthetic evidence markers are retained and displayed prominently. No
marker means only that none was found, not that provider origin was authenticated.
Review-ledger verification and evidence freshness are frozen at assessment time;
export does not refresh evidence or apply newer mapping decisions. Generation
hashes and bundle hashes detect file changes but are not signatures or independent
attestations. Retain a trusted archive digest separately when sharing it.

The destination must be a new ZIP outside the lake. Existing files and symlinks
are never overwritten. A temporary private file is completed and synced before
exclusive publication; failed writes leave no partial destination. The output is
mode `0600`, and the filesystem must support hard links in its parent directory.

Export verification streams generation artifacts, so time grows with lake size.
The report uses catalog-sized summaries rather than loading per-asset result
arrays, and scans source evidence for explicit synthetic markers. This is an
export workflow, not a constant-time request or a capacity benchmark.

## Validation

`tests/test_framework_report.py` covers distinct coverage counts, missing catalog
rows, framework filters, generation pinning during publication, tenant mismatch,
corruption, synthetic provenance, HTML escaping, archive hashes, and failed writes.
Local rendering checks cover the overview and expanded requirement tables at
desktop and mobile widths. These checks do not qualify any cloud provider or
third-party GRC consumer.
