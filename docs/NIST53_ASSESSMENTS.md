# NIST 800-53 assessment expansion

This expansion adds 381 **proposed, source-native safeguards** for previously
unmapped NIST SP 800-53 Rev. 5 obligations. It brings catalog mapping coverage to
1,803 of 2,252 requirements (80.1%). Reviewed coverage remains 339 (15.1%).
It does not establish 381 cross-framework equivalences or completed assessments.

The scope closes the remaining catalog gaps in nine NIST families:

| Family                                        | New mapped requirements |
| --------------------------------------------- | ----------------------: |
| Access Control (AC)                           |                      96 |
| Identification and Authentication (IA)        |                      35 |
| Audit and Accountability (AU)                 |                      40 |
| Configuration Management (CM)                 |                      32 |
| System and Information Integrity (SI)         |                      87 |
| Incident Response (IR)                        |                      27 |
| Contingency Planning (CP)                     |                      26 |
| Maintenance (MA)                              |                      23 |
| Assessment, Authorization and Monitoring (CA) |                      15 |

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
Existing common safeguards and their reviews are unchanged. A future reusable
cross-framework mapping requires its own rationale and human review.

To reproduce the extraction, download the pinned catalog above, then run:

```bash
PYTHONPATH=src python tools/sync_nist53_assessment_safeguards.py --source NIST_SP-800-53_rev5_catalog.json --check
```

The command verifies the complete source digest and version, rejects withdrawn or
missing targets and unresolved parameters, and compares the resulting definitions
with the checked-in safeguards. Without `--check`, it regenerates only this
expansion. It refuses to overwrite definitions that have recorded human reviews.
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
The remaining target is at least 1,126 reviewed requirements (50%): 787 more than
the current catalog. Unrelated PR approvals do not supply those mapping decisions.
