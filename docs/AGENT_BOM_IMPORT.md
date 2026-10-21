# Import Agent-Bom findings

Bring an existing Agent-Bom JSON scan report into GRC Lake without repeating its
cloud collection. This current-source CLI imports **AI-BOM report schema 1.0**
into canonical raw evidence. It does not install Agent-Bom, call providers, or
register another live connector. See [release status](RELEASE_READINESS.md) for
availability in published packages.

## Import and inspect

Use a report you are authorized to process. Choose the tenant and a report scope
that identifies the scanned repository, image, or environment. Keep the original
report securely: the imported references identify its SHA-256 digest and finding
positions, but GRC Lake does not copy the complete source report.

```bash
grc-lake ingestion import-agent-bom \
  --report ./agent-bom-report.json \
  --out ./agent-bom-evidence.jsonl \
  --tenant-id example-company \
  --asset-id repo:example-service

grc-lake validate --raw ./agent-bom-evidence.jsonl
```

The output contains one scan receipt and one observation per finding. No control
is selected by default. To explicitly associate vulnerability observations with
a catalog control, supply repeatable `--control` flags. For example, after
reviewing the relevance of SOC2-CC7.1 to your scope:

```bash
grc-lake ingestion import-agent-bom \
  --report ./agent-bom-report.json \
  --out ./agent-bom-scoped-evidence.jsonl \
  --tenant-id example-company \
  --asset-id repo:example-service \
  --control SOC2-CC7.1

grc-lake ingestion normalize \
  --raw ./agent-bom-scoped-evidence.jsonl \
  --out ./agent-bom-lake \
  --tenant-id example-company
```

Use a separate lake for this first import. Normalization assesses the supplied
input as a complete dataset; it does not append the report to an existing lake.
The `--incremental` option also expects the complete input dataset.

For the bundled synthetic report, use
`--report tests/fixtures/agent_bom/report.json --synthetic`. The flag carries
synthetic provenance into the lake and exports. Input `synthetic: true` or
`demo: true` markers also propagate. Unmarked reports remain user-supplied,
unauthenticated observations; absence of a synthetic marker proves nothing about
provider origin.

## Assessment boundaries

| Imported observation                                                                                                               | GRC state and mapping                                                                 |
| ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| CVE or malicious-package finding, rated severity, explicit active lifecycle (`new`, `open`, `unchanged`, `reopened`), unsuppressed | `open`; caller-selected controls only; eligible for existing vulnerability evaluation |
| Suppressed, resolved, missing/unknown lifecycle, or unrated vulnerability                                                          | `not_evaluated`; explicit bindings retained for review, never a passing result        |
| Other finding types, including cloud benchmark failures and collection errors                                                      | `not_evaluated`; no automatic control binding                                         |
| Scan receipt, including an empty complete scan                                                                                     | `not_evaluated`; no control binding                                                   |

A finding is an observation, not proof that an entire control operated. Upstream
framework tags, closure states, and scan completeness never approve CCF mappings
or establish framework coverage. Existing GRC rules, evidence freshness, scoped
workpapers, and [mapping review](MAPPING_REVIEW.md) still govern assessment.
A partial or failed scan can contain useful observed vulnerabilities; it cannot
prove that the unobserved population is safe. Scan outcome and warning count are
retained as producer claims, not independent collection qualification.

## Data and write contract

- Input is bounded to 32 MiB and 50,000 findings. Duplicate JSON keys, duplicate
  finding identities, unsupported schema versions, malformed fields, missing or
  timezone-free scan timestamps, and future scan timestamps reject the whole
  import before publication. Finding schema `1` is supported when present.
- Tenant and report asset scope come from CLI arguments. Importing into another
  tenant or scope produces distinct event identities. Identical inputs and
  bindings replay deterministically. Changed report content has a different hash.
- Evidence time stays at the report's `generated_at`; importing old reports does
  not make them fresh. Finding occurrence IDs, hashed upstream asset identity,
  recognized CVE IDs, severity, lifecycle, suppression, and scan outcome are
  retained. Free-text descriptions, credentials, commands, upstream framework
  tags, and warning bodies are excluded.
- Output is a complete private file (mode `0600`) published without overwriting
  existing paths, including symlinks. Failed writes leave no partial output.
  Published assessment generations remain immutable. The destination filesystem
  must support hard links within the output directory.
- The CLI returns a JSON import receipt with the source hash, finding/event
  counts, bound vulnerability count, reported scan outcome, and synthetic marker.
  A hash supports integrity checking; it does not authenticate the producer.

## Compatibility evidence

The synthetic fixture in `tests/fixtures/agent_bom/report.json` was emitted by
Agent-Bom's `to_json(AIBOMReport(...))` at
[commit f95700c](https://github.com/koda-ai-studio/agent-bom/tree/f95700cfd7c5b10cc0c86294a2585b75dc0dc279).
Only the report envelope and full finding records are retained; unrelated
inventory and summary sections are omitted. The producer contracts are `src/agent_bom/output/json_fmt.py` and
`src/agent_bom/domain/finding_model.py`. Its two fabricated findings cover an
active CVE and a cloud collection error with null lifecycle. Report time, scope,
IDs, and version are synthetic; external catalog metadata was stubbed and network
connections were disabled during generation. The adjacent `generate.py` records
how to reproduce it using that Agent-Bom checkout.

`tests/test_agent_bom_import.py` checks this fixture, replay, caller scope,
malformed inputs, write failures, immutable output, and normalization/provenance.
These are offline contract tests, not evidence of credentialed provider coverage
or production qualification. Agent-Bom is not a GRC Lake runtime dependency.
