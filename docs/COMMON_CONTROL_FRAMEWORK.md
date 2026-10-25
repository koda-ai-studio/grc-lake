# Common Control Framework

A Common Control Framework consolidates many regulatory requirements into one set
of operational safeguards. You operate the safeguard; framework coverage is
derived from it.

GRC Lake is adopting this model. This document describes the target, what exists
today, and how the rest gets there.

The live, generated **[Framework Coverage Matrix](FRAMEWORK_COVERAGE.md)** shows
per-framework mapping coverage split into mapped and reviewed requirements.
The gap is the mapping-review backlog. A reviewed crosswalk is not a test of
operating effectiveness or an auditor acceptance decision. The API retains
`evaluatable` and `attestable` field names for compatibility.

## Why the catalog alone is not a CCF

`controls/catalog.json` is framework-first: 2282 requirements, each carrying its
own `framework_id` **and its own `evidence_requirement`** — 2282 distinct evidence
statements for 2282 controls, none shared.

That last number is the whole problem. Because no two requirements share an
evidence statement, answering SOC 2, ISO 27001, and FedRAMP means answering the
same operational question three times, in three places, with three review trails.

`mappings/framework_equivalence.json` was a first attempt at relief, linking
requirements that address the same theme. But it is a crosswalk _laid over_ a
framework-first catalog. It annotates the duplication instead of removing it.

## The model

A **safeguard** is the operated object. It carries one evidence requirement, one
evaluation rule, one owner — and it satisfies many framework requirements.

```
safeguard  SG-IDENTITY-001  "Logical access and MFA"
  evidence_requirement   (one statement, operated once)
  evaluation_rule        (one test)
  satisfies
    SOC2-CC6.1            soc2              primary
    ISO27001-A.5.15       iso-27001-2022    equivalent
    NIST-CSF-PR.AA-01     nist-csf-2.0      equivalent
    FEDRAMP-AC-2          fedramp-moderate  equivalent
    CIS-AWS-1.10          cis_aws           equivalent
    HIPAA-164.308(a)(4)   hipaa-security-rule equivalent
```

Six requirements, one thing to operate.

### The relationship is many-to-many, in both directions

One safeguard satisfying many requirements is the point. The reverse also
happens: **SOC2 CC7.2 and PCI-DSS-10 each need two safeguards** — detection _and_
audit logging.

That forces a semantic decision, and it is the one worth arguing about:

> A framework requirement is met only when **every** safeguard mapped to it passes.

The alternative — any one passing is enough — would let a green logging safeguard
report a monitoring requirement as satisfied. That is a false attestation reaching
an auditor, which is the failure this system exists to prevent.

`requirement_status()` also distinguishes **`unmapped`** from `fail`. "We have not
modelled this yet" and "we tested it and it failed" are different answers, and
collapsing them would overstate both coverage and failure.

## Control families and categories

Every safeguard belongs to exactly one family defined in
[`controls/families.json`](../controls/families.json); the validator rejects any
other value. Each family records the NIST SP 800-53 families and CIS Controls it
corresponds to, and `GET /api/v1/ccf/coverage` returns those definitions with the
family ledger.

Above the families sits a small, stable set of ten **categories**, also defined in
`controls/families.json`. Each family names exactly one category, and the
validator rejects a family with a missing or unknown category, a duplicate
category id, or a category no family uses. Categories are a navigation and
roll-up layer only: they carry no evaluation rule and no mapping of their own.
`GET /api/v1/ccf/coverage` returns a `categories` ledger (distinct requirement and
framework counts, reviewed and proposed mappings), every family row carries
`category_id` and `category_label`, `grc-lake frameworks safeguards
--format table` prints families under their category, and each OSCAL component
carries a `trustops-category` property.

A family is placed by what it operates, not by which framework asked for it. AI
safeguards that operate a general control, such as access control on inference
endpoints or AI incident handling, sit in that control's family (Identity and
access, Incident response) rather than in AI governance, so they roll up with the
rest of that control.

| Category                     | Family                    | ID                         | Safeguards | NIST SP 800-53 families | CIS Controls |
| ---------------------------- | ------------------------- | -------------------------- | ---------: | ----------------------- | ------------ |
| Governance and risk          | Risk management           | `risk-management`          |         71 | RA, CA, PM              | 18           |
| Governance and risk          | Governance                | `governance`               |         91 | PL, PM                  | —            |
| Identity and access          | Identity and access       | `identity`                 |        198 | AC, IA                  | 5, 6         |
| Data protection and privacy  | Data protection           | `data-protection`          |        165 | SC, MP                  | 1, 3         |
| Data protection and privacy  | Privacy                   | `privacy`                  |         29 | PT                      | —            |
| Secure engineering           | Change management         | `change-management`        |          5 | CM                      | —            |
| Secure engineering           | Secure development        | `secure-development`       |        112 | SA                      | 16           |
| Secure engineering           | Secure architecture       | `secure-architecture`      |          4 | SA, SC                  | —            |
| Infrastructure security      | Configuration management  | `configuration-management` |         62 | CM                      | 2, 4         |
| Infrastructure security      | Vulnerability management  | `vulnerability-management` |          3 | RA, SI                  | 7            |
| Infrastructure security      | Network security          | `network-security`         |          1 | SC                      | 12           |
| Detection and response       | Detection                 | `detection`                |          3 | SI                      | 10, 13       |
| Detection and response       | Audit logging             | `logging`                  |         59 | AU                      | 8            |
| Detection and response       | Incident response         | `incident-response`        |         50 | IR                      | 17           |
| Resilience and integrity     | Availability and recovery | `availability`             |         54 | CP                      | 11           |
| Resilience and integrity     | System maintenance        | `system-maintenance`       |         32 | MA                      | —            |
| Resilience and integrity     | Processing integrity      | `processing-integrity`     |        105 | SI                      | —            |
| Third-party and supply chain | Third-party risk          | `third-party-risk`         |         33 | SR, SA                  | 15           |
| People and physical          | People security           | `people-security`          |         42 | AT, PS                  | 14           |
| People and physical          | Physical security         | `physical-security`        |         55 | PE                      | —            |
| AI governance                | AI governance             | `ai-governance`            |         21 | —                       | —            |

## Where it stands

```
$ grc-lake frameworks safeguards --format table
1195 safeguards map 2196 of 2282 requirements (96.2%) — 1163 maintainer-reviewed (339 rest only on legacy reviews with no recorded reviewer), 0 org-reviewed (51.0% attestable), 1033 proposed; 0 mapping(s) rejected by the org
```

A mapping is **reviewed** once a human has confirmed the requirements are the
same obligation. **Proposed** mappings are unapproved candidates, including
source-native assessment contracts and crosswalk proposals, and are
reported separately, because a compliance product must never count unconfirmed
work as attested coverage. `safeguards_by_requirement(reviewed_only=True)` is
what attestation should read — so "SOC 2 is fully mapped" and "SOC 2 is fully
reviewed" are different claims, and only the second is one to make to an
auditor.

Curation is ordered by what teams are actually audited and certified against.

The family ledger is available through `grc-lake frameworks safeguards`
and `GET /api/v1/ccf/coverage`. It groups the operated safeguards by their
`risk_domain`, then reports the frameworks touched plus reviewed and proposed
mapping counts. A family with proposed mappings is **evaluatable**, not
attestable; the endpoint keeps those states separate so a broad family view
cannot become a false certification claim.

| Framework           | Requirements | Mapped |    Pct |
| ------------------- | -----------: | -----: | -----: |
| cis-controls-v8.1   |           18 |     15 |  83.3% |
| cis_aws             |           62 |     51 |  82.3% |
| cmmc-2-level2       |          110 |    110 | 100.0% |
| dora-2022-2554      |           99 |     79 |  79.8% |
| eu-ai-act-2024-1689 |           16 |     16 | 100.0% |
| fedramp-moderate    |          287 |    262 |  91.3% |
| gdpr-2016-679       |           20 |     20 | 100.0% |
| hipaa-security-rule |           24 |     19 |  79.2% |
| iso-27001-2022      |           93 |     93 | 100.0% |
| iso-27001-isms-2022 |           30 |     30 | 100.0% |
| iso-27017-2015      |           47 |     44 |  93.6% |
| iso-27701-2025      |           10 |      8 |  80.0% |
| iso-42001-2023      |           40 |     40 | 100.0% |
| nis2-2022-2555      |           17 |     17 | 100.0% |
| nist-800-171-rev3   |           97 |     85 |  87.6% |
| nist-800-53-rev5    |         1014 |   1014 | 100.0% |
| nist-ai-rmf         |           72 |     69 |  95.8% |
| nist-csf-2.0        |          106 |    106 | 100.0% |
| nist-rmf-800-37r2   |           47 |     46 |  97.9% |
| pci-dss-v4          |           12 |     11 |  91.7% |
| soc2                |           61 |     61 | 100.0% |

### Broadest safeguards

A broad safeguard answers many requirements with one generic evidence rule.
That gives shallow assurance per requirement:
a pass on one does not demonstrate each requirement it maps to,
because the rule checks the shared theme, not each requirement's specific
obligation. Read the per-requirement mapping and its
review state before relying on a broad safeguard for a given requirement. A
ratchet test keeps these safeguards from growing and caps every other safeguard,
new ones included, at 20 requirements. Narrower safeguards are the way to add
depth.

Reviewed and proposed count coverage-contributing mappings; supporting and
inherited relationships are context and appear in neither column. "Legacy, no
reviewer" is the part of Reviewed that predates decision receipts and records no
reviewer. Generated by `tools/sync_ccf_doc.py`.

<!-- broadest-safeguards:start -->

| Safeguard                 | Title                                                 | Requirements | Frameworks | Reviewed | Legacy, no reviewer | Proposed |
| ------------------------- | ----------------------------------------------------- | -----------: | ---------: | -------: | ------------------: | -------: |
| `SG-IDENTITY-001`         | Logical access and MFA                                |          153 |         14 |      103 |                  81 |       49 |
| `SG-LOGGING-001`          | Audit logging and traceability                        |           78 |         14 |       57 |                  45 |       21 |
| `SG-DATAPROTECTION-001`   | Encryption and data protection                        |           77 |         15 |       51 |                  37 |       26 |
| `SG-PHYSICAL-001`         | Physical and environmental security                   |           75 |         10 |       41 |                  29 |       34 |
| `SG-AVAILABILITY-001`     | Backup and availability                               |           73 |         12 |       27 |                  13 |       46 |
| `SG-GOVERNANCE-002`       | Governance and control environment                    |           72 |         11 |       16 |                   0 |       56 |
| `SG-DETECTION-001`        | Monitoring and incident detection                     |           71 |         15 |       34 |                  26 |       37 |
| `SG-NETWORK-001`          | Network security controls                             |           62 |         11 |       22 |                  15 |       40 |
| `SG-THIRDPARTYRISK-001`   | Vendor and third-party risk                           |           55 |         15 |       21 |                  11 |       34 |
| `SG-POLICYMANAGEMENT-001` | Security policy set approved, published, and reviewed |           51 |         10 |        9 |                   0 |       42 |

339 of the 1163 reviewed requirements rest only on legacy reviews with no recorded reviewer (340 mappings, listed with their originating commits in [the legacy record](../controls/reviews/legacy-unattributed.json)); the other 824 have a decision receipt or an org decision.
<!-- broadest-safeguards:end -->

### What a safeguard applies to

Evaluation targets resources, not frameworks. The catalog already records
`asset_types` on all 2282 requirements — `iam_role`, `data_store`, `ai_model`,
`audit_log`, `cloud_resource` and 15 more — and a safeguard carries the union of
what its members apply to. `safeguards_for_asset_type("iam_role")` returns the
19 safeguards that bear on IAM roles.

Without that a safeguard cannot be pointed at anything, which would make the
operated object undeployable. The validator rejects a safeguard with no asset
types, and a test asserts each one still matches its members rather than
drifting as curation moves.

## The real ceiling is the catalog, not the curation

Some titles still contain identifier-only or boilerplate descriptions,
all ISO 27001 Annex A entries. ISO text is licensed: those need short internal
summaries or licensed access, and must not be copied into this public
repository. The NIST AI RMF titles now use the official subcategory statements
from the pinned NIST AI 100-1 PDF (prior formulaic titles remain in control
history).

NIST SP 800-53 mappings that duplicate a human-reviewed FedRAMP Moderate
mapping inherit that review, because a FedRAMP Moderate control is the 800-53
control of the same identifier. Each inherited mapping records
`review_basis.inherited_from`, and a test keeps the two in lockstep.

The CSF 2.0 catalog now uses the 106 identifiers and outcomes from the pinned
[NIST publication](https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf).
Subcategory numbers are not consecutive. The previous generator produced 13
invalid identifiers and omitted 13 official ones despite matching the total
count. Those prior definitions remain in control history; they are not silently
remapped to different outcomes. The new source reconciliation is proposed and
does not claim expert review or full compliance automation.

## Review and evaluation boundaries

`grc-lake frameworks review-queue` lists proposed mappings, with
framework and risk-domain filters and source references. The
`get_mapping_review_queue` MCP tool exposes the same review ledger. A reviewer
must confirm semantic equivalence; source provenance alone does not do so.
Your organization records that confirmation, or a rejection, per tenant; see
[Mapping review](MAPPING_REVIEW.md).

The pipeline publishes `gold/ccf_assessment.json` alongside framework-control
posture. Evidence must explicitly name `safeguard_ids`; framework tags never
implicitly assert a safeguard. The engine indexes evidence by safeguard and
asset, runs the declared rule once per binding, and derives requirement results
from every reviewed safeguard. Missing evidence for an applicable observed
asset, ambiguous asset types, unknown outcomes, stale evidence, pending mappings,
or an unverifiable review log block a requirement pass. A known failure remains
a failure even when other evidence is incomplete. Rejected links are excluded;
requirements without remaining links are `unmapped`.

Read results through the Frameworks page, `GET /api/v1/ccf/assessment`, the
`get_ccf_assessment` MCP tool, or:

```bash
grc-lake frameworks assessment --lake ./lake
```

The retained assessment includes event IDs and evidence hashes for each assessed
asset. The summary endpoint omits asset detail; page through
`GET /api/v1/ccf/asset-results?limit=100&offset=0` or `list_ccf_asset_results`
for those rows. Current generations serve summaries and asset pages from a
pinned, indexed SQLite projection, bounding both page materialization and response
size. Legacy generations without a declared projection fall back to the JSON
artifact. A declared projection that is missing or unreadable fails closed.
Retain the JSON generation for CCF results: the existing SQL sink tables do not
carry the CCF assessment. Parquet preserves normalized safeguard bindings.
The assessment is sealed with the exact safeguard definitions and review overlay used in
that generation. Review changes invalidate an incremental evaluation even when
raw evidence is unchanged; readers see the last published assessment until the
next evaluation.

**Scope is observed assets.** This does not establish a complete asset inventory,
prove an imported assertion, or certify an organization. Connector observations
without explicit safeguard outcomes remain unevaluated. Lake mappings can bind
safeguards per row; the [OCSF presets](BRING_YOUR_OWN_LAKE.md#ocsf-events-in-the-common-control-framework)
do so for sign-in MFA, privilege grants, group membership grants,
vulnerability findings, and configuration checks. Existing framework
posture, readiness scores, and OSCAL findings continue to describe the separate
framework-control lane; they are not silently replaced with CCF results.

[NIST SP 800-53A](https://csrc.nist.gov/pubs/sp/800/53/a/r5/final)
describes assessment procedures using examination, interview, and testing.
Crosswalk review is only one input to that assessment work.

## Schema

`controls/safeguards.json`, `schema: trustops.safeguards.v1`.

| Field                        | Meaning                                                                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| `safeguard_id`               | `SG-<RISKDOMAIN>-<NNN>`, stable                                                                         |
| `title`                      | What the safeguard does                                                                                 |
| `risk_domain`                | Shared taxonomy with the control catalog                                                                |
| `objective`                  | Why these requirements are genuinely the same thing                                                     |
| `evidence_requirement`       | The single statement this safeguard proves                                                              |
| `evaluation_rule`            | The single test                                                                                         |
| `owner`, `frequency`         | Who operates it, how often                                                                              |
| `satisfies[]`                | `control_id`, `framework_id`, `role` (`primary`/`equivalent`/`supporting`/`inherited`), `review_status` |
| `mapping_source`             | Optional source name, HTTPS URL, SHA-256, and exact locator for a crosswalk                             |
| `satisfies[].mapping_source` | Per-mapping provenance; overrides safeguard-level provenance in review output                           |

Exactly one member carries `role: primary` — the requirement whose wording the
safeguard is drafted against. Every `control_id` must exist in the catalog; the
validator rejects claimed coverage that does not resolve. When a safeguard has
multiple source locators, provenance belongs on each mapping. The review queue
uses that member-level source first and falls back to the safeguard-level source.

For query behavior, compatibility, and memory boundaries, see [CCF assessment reads](CCF_READS.md).

## Auditor workpapers

[Control test plans](CONTROL_TEST_WORKPAPERS.md) distinguish design documentation
from period samples and preserve every observed deviation. [Population
reconciliation](POPULATION_RECONCILIATION.md) compares the generation with a
declared inventory and collection receipts. Neither silently changes the CCF
assessment's observed-population scope. The [auditor walkthrough](AUDITOR_WALKTHROUGH.md)
combines these results, evidence hashes, and remediation receipts in a reproducible
workpaper with an independent authenticated review decision.

### Relationship roles and assessment context

`primary` and `equivalent` relationships contribute to evaluated coverage;
reviewed relationships can contribute to attestable coverage. `supporting` and
`inherited` relationships record relevant evidence or provider responsibility.
They remain visible in mapping review and CCF assessment JSON but do not add
coverage, serve as reviewed equivalence anchors, or export as OSCAL implemented
requirements. Reviewing the relationship does not change that boundary.

An inherited mapping alone does not establish provider control effectiveness.
Period-bound workpapers can record explicit `not_applicable`, `inherited`, or
`compensating` assessment context with evidence and an independent review. See
[the workpaper contract](AUDITOR_WALKTHROUGH.md#assessment-context).

### Maintainer source-batch review

The [2026-10-14 review record](../controls/reviews/2026-10-14-source-batches.json)
contains maintainer approval for 33 source-review batches: 885 source-backed
mapping relationships covering 806 distinct requirements. Each relationship is
bound to its inspected semantic digest and original catalog commit.

The source packets contain requirement references, mapping roles, source locators,
safeguard objectives, evidence requirements and inspected hashes. Their base
catalog is commit `40ce68a3b0ebe056b6f5565d4638d328e734d64d`. Source-native NIST
contracts retain pinned source statements, assessment objectives and parameters;
see the [source and derivation record](NIST53_ASSESSMENTS.md#source-and-derivation).

Automated checks verify the recorded mapping identities and hashes, reconcile
distinct requirement counts, and exclude stale versions from coverage. Source
extraction checks compare all 1,014 NIST assessment contracts with the authoritative
catalog. These checks establish record consistency, not mapping correctness or
operating effectiveness. The timestamp records the batch decision, not individual
inspection times.

The aggregate reviewed percentage records maintainer mapping decisions. It does
not establish independent assurance or equal review depth across frameworks;
consult the [per-framework coverage matrix](FRAMEWORK_COVERAGE.md). SOC 2,
ISO 27001 and ISO 42001 retain review gaps despite the aggregate milestone.

The review adds 789 currently credited requirements, taking reviewed coverage to
1,128 of 2,252 (50.1%). Seventeen approved requirements remain uncredited because
their mapping versions are stale. Their original version pins are preserved.
Mapped coverage remains 1,803 of 2,252 (80.1%). Source-less alternatives and
supporting relationships receive no additional coverage credit. Approval does
not establish operating effectiveness or turn missing evidence into a pass.

### SOC 2 and ISO repair decisions

After the source-batch milestone above, the maintainer approved 35 repaired
proposals: 23 SOC 2, seven ISO 27001 and five ISO 42001. The
[review record](MAPPING_REVIEW.md#pending-soc-2-and-iso-review)
links the inspected contracts and source references. Release 0.3.6 has 1,163 reviewed requirements (51.6%); mapping coverage
remains 1,803 (80.1%). These changes are included in the published 0.3.6 release.
Unapproved alternatives remain proposed, and operational evidence is still required.

### NIST SP 800-171 Rev. 3 operational safeguards

`SG-INFORMATIONEXCHANGE-001` covers requirement 03.12.05 through explicitly
assessed CUI exchange agreements, interface/security responsibilities, and an
organization-defined review frequency. `SG-PERSONNELSCREENING-001` covers 03.09.01
through screening before access and rescreening under defined conditions.
Personnel evidence should retain assessment references and completion outcomes,
not sensitive investigation details.

Both primary mappings have maintainer approval. Their 800-53/FedRAMP CA-3 and PS-3 source-control links
are supporting context, not claims of full control equivalence. Observed
connectivity or active accounts do not establish either safeguard, and passing
safeguard evidence does not make a proposed requirement mapping attestable.
Refresh the manifest's mapping-gap list with
`python tools/sync_nist_800_171r3.py --refresh-coverage-only`; this preserves the
pinned source data and hashes while deriving gaps from current implementation
mappings. Source: [NIST SP 800-171 Rev. 3](https://csrc.nist.gov/pubs/sp/800/171/r3/final).
