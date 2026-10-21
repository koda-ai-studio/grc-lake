# ISO 27001 management-clause assessments

GRC Lake separates two catalog scopes for the same standard:

| Pack                                       | Catalogued |      Mapped | Newly granted review credit |
| ------------------------------------------ | ---------: | ----------: | --------------------------: |
| `iso-27001-2022` — Annex A                 |         93 |          93 |                           0 |
| `iso-27001-isms-2022` — management clauses |         30 | 30 proposed |                           0 |

The management pack adds the leaf clause identifiers in clauses 4–10. Parent
headings are excluded to avoid counting both a group and its children. It is a
companion scope, not another standard or certification. Existing Annex A
decisions remain unchanged; current effective reviews are in the generated
[coverage ledger](FRAMEWORK_COVERAGE.md).

Each `SG-ISMS-*` safeguard has one clause target and a distinct
`isms_<clause>_assessment` evidence type. The GRC Lake prompts describe records
an assessor can inspect, including scope, owner, assessment period, evidence
references, tests, exceptions, and remaining uncertainty. These original
procedures must be validated against the applicable standard before approval.
They are not reproduced normative requirements or automated clause-completeness
checks. A generic policy, an unbound record, stale evidence, or an observed-only
record cannot produce a passing safeguard result. Even a passing assessor record
does not grant a requirement pass while its mapping remains proposed.

## Source references and limits

- The [ISO publication record](https://www.iso.org/standard/27001) identifies the
  edition and amendment. No licensed standard text is committed.
- The [GSO public contents preview](https://gso-sims-preview-doc-aws.s3-eu-west-1.amazonaws.com/iso-iec-27001-2022-en.html)
  supplies clause identifiers. Its retrieved bytes are SHA-256 pinned in the
  manifest. This preview omits 6.3; it is not treated as a complete source.
- The [NEN revision overview](https://www.nen.nl/en/nieuws/wijzigingen-iso-iec-27001-2022-ten-opzichte-van-2013/)
  confirms clause 6.3 in its change-planning section. Its publication text was
  checked and its retrieved HTML snapshot is SHA-256 pinned.
- The [ISO/IAF February 2024 communiqué](https://www.iso.org/files/live/sites/isoorg/files/standards/popular_standards/management_systems/ISO-IAF%20Joint%20Communique%20Feb%202024.pdf)
  supports climate considerations in the context and stakeholder prompts for
  4.1 and 4.2. Its publication text was checked; downloadable bytes are not pinned.

Public references establish identifier scope and context. They do not approve
the proposed assessment contracts or establish normative completeness. Reviewers
must assess the applicable requirements, amendments, organizational scope, and
evidence before recording decisions. Cataloguing and mapping every identifier
does not establish conformity, certification, or operating effectiveness.

## Reproduce and review

From a source checkout, with both original public source snapshots retained locally:

```sh
uv run grc-lake frameworks sync-packs --pack iso-27001-isms
uv run python tools/sync_iso27001_isms.py --source /path/to/preview.html --clause-source /path/to/nen.html
uv run python tools/sync_iso27001_isms.py --source /path/to/preview.html --clause-source /path/to/nen.html --check
uv run grc-lake frameworks review packet --framework iso-27001-isms-2022 --out build/isms-review.json
```

The generator checks both source hashes, unique leaf identifiers, catalog ownership,
and existing contracts. A differing existing contract requires explicit
reconciliation rather than silent replacement. Re-running generation adds no
duplicates and records no review decisions. The review packet retains evidence
requirements, source limitations, and empty decision fields.

Keep the 30 management clauses separate from the 93 Annex A controls when
presenting coverage. SOC 2, NIST CSF, and NIST SP 800-53 counts and review states
are unchanged by this addition.
