# NIST 800-53 assessment contracts

All **1,014 active NIST SP 800-53 controls and enhancements** have an individual
source-native assessment contract, across all 20 families in the pinned 5.2.0
catalog. The expansion adds 633 contracts to the existing 381. Of these, 348
requirements previously had no safeguard mapping; 285 already had crosswalk
mappings and now also have a direct assessment path.

The original 381 source-native mapping reviews are preserved. The 633 additions
remain **proposed**. NIST mapped coverage is 1,014/1,014; reviewed coverage remains
495/1,014 (381 source-native and 114 crosswalk-reviewed). These figures measure
catalog and mapping support, not automated testing or a company's compliance.
See the [coverage matrix](FRAMEWORK_COVERAGE.md) for the other frameworks.

| NIST family | Assessment contracts |
| ----------- | -------------------: |
| AC          |                  131 |
| AT          |                   15 |
| AU          |                   56 |
| CA          |                   25 |
| CM          |                   56 |
| CP          |                   49 |
| IA          |                   59 |
| IR          |                   40 |
| MA          |                   28 |
| MP          |                   20 |
| PE          |                   51 |
| PL          |                   11 |
| PM          |                   37 |
| PS          |                   17 |
| PT          |                   21 |
| RA          |                   22 |
| SA          |                  108 |
| SC          |                  139 |
| SI          |                  102 |
| SR          |                   27 |

## Source and derivation

The input is the official NIST OSCAL 5.2.0 catalog at commit
`78650f02ad9321bb7b817846f8fbd4f2bcd620de` of
[usnistgov/oscal-content](https://github.com/usnistgov/oscal-content/tree/78650f02ad9321bb7b817846f8fbd4f2bcd620de/nist.gov/SP800-53/rev5/json).
Its SHA-256 is
`01f37cf90ea99d92242c936cbfbdebcc338eef1f71454e2acac36cc56e9bc062`.
The selected identifiers are in `controls/nist53_assessment_expansion.json`.

Each safeguard retains its obligation's source statement, assessment objectives,
assessment objects and required dependency references. Organization-defined
parameters retain their identifiers, definitions and selection cardinality.
Each has exactly one primary mapping and a distinct evidence type, such as
`nist53_ac_2_6_assessment`. A general IAM review cannot establish dynamic privilege
management merely because both concern access control.

Obligations are kept separate because distinct enhancements are not interchangeable.
The number of source-native safeguards follows the standard's clause counts;
Access Control and Identification/Authentication therefore have more entries
than smaller families. Each source family must match the governed CCF taxonomy.
The existing 15% anti-catch-all distribution check remains on reusable common
safeguards; native contracts are checked against their actual source family.
The expansion left existing common safeguards and their reviews unchanged. A future reusable
cross-framework mapping requires its own rationale and human review.

To reproduce the extraction, download the pinned catalog above, then run:

```bash
PYTHONPATH=src python tools/sync_nist53_assessment_safeguards.py --source NIST_SP-800-53_rev5_catalog.json --check
```

The command verifies the complete source digest and version, rejects withdrawn or
missing targets and unresolved parameters, and compares the resulting definitions
with the checked-in safeguards, excluding human review metadata from that
source-contract comparison. Without `--check`, it regenerates only this
expansion. Exact existing definitions retain their review metadata. It refuses
to change or remove a contract with a recorded human review; new entries remain
proposed. Repeated generation with the same source is idempotent.
Catalog lock, coverage documents and golden artifacts must then be regenerated
with their owning commands.

## Assessment and review boundaries

These evidence types describe **assessor-provided records**. No connector is
claimed to extract them automatically. A qualified assessor must establish the
applicable scope, parent prerequisites, organization-defined values, assessment
period and evidence supporting every objective. The evaluation engine checks
bindings, typed evidence, freshness and supplied outcomes; it does not infer that
a narrative or an imported pass flag proves every source clause.

Every mapping starts proposed with no reviewer or approval timestamp. Even fresh,
passing, explicitly bound assessment evidence cannot make the mapped requirement
pass until its mapping is reviewed. Missing, stale, unrelated, observed-only or
unknown evidence does not become passing evidence after review.

Reviewers should compare each operating contract with its cited source and record
approve, needs-changes or reject with a rationale. Approval of a source-native
mapping establishes that contract's mapping, not a cross-framework equivalence,
the assessed organization's implementation, population completeness or certification.
The [maintainer decision receipt](../controls/reviews/2026-10-14-source-batches.json)
records the approval of all 33 prepared source-review batches, including the original
381 safeguards. That receipt does not approve the 633 later additions. Stale version pins still prevent review credit for 17 other approved
requirements. Unrelated PR approvals do not supply mapping decisions.
