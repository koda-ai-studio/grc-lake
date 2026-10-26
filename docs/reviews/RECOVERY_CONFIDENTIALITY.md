# Recovery and confidentiality: focused review

**Decision recorded.** On 2026-10-25 the maintainer approved both candidates below
as part of the [SOC 2 and ISO 27001 batch decision](../../controls/reviews/2026-10-25-soc2-iso27001-batch.json).
That decision did not adopt the engineering recommendations on this page and
records no separate rationale for either mapping. Both mappings now count as
maintainer-reviewed. The substantiation described below is still what an
assessor should require before relying on an `SG-AVAILABILITY-001` or
`SG-DATAINVENTORY-001` result for these criteria.

The [archived candidate packet](stability-review-packet.json) holds the two
requirements as they were before that decision, with exact operating contracts
and review fingerprints. It records no human decisions. The
[archived SOC 2 and ISO 27001 queue](2026-10-25-soc2-iso27001-pending-queue.json)
keeps the source locators and questions that were presented. Vendor guidance is
not the full normative requirement.

## Recovery testing: SOC2-A1.3

Candidate: `SG-AVAILABILITY-001` (Backup and availability).

The current safeguard asks for current environmental-protection and backup
evidence with no high-risk failure. That can demonstrate backup activity without
demonstrating a recovery exercise. The candidate therefore needs changes or
additional substantiation before approval.

A reviewer should examine the recovery objectives and declared system scope,
exercise procedure, actual restoration results, integrity and completeness
checks, elapsed recovery time, exceptions and corrective-action follow-up.
A configured schedule or a successful backup job alone is insufficient evidence
for the recovery-testing question. An imported pass flag does not establish that
these checks occurred.

## Confidential-data protection: SOC2-C1.1

Candidate: `SG-DATAINVENTORY-001` (Data inventory and records of processing).

The current safeguard asks for fresh processing-activity records covering the
in-scope systems. An inventory identifies data but does not by itself demonstrate
protection. This candidate also needs changes or additional substantiation before
approval.

A reviewer should examine the confidential-data inventory and classification,
applicable protection requirements, the access and handling restrictions for
that same scope, enforcement tests, exceptions and treatment decisions. Separate
population completeness from a tested sample. The presence of an inventory or
an imported pass flag is not proof of protection.

## Engineering recommendations and the recorded decision

These were engineering review recommendations, not human mapping decisions. The
maintainer's batch decision is the recorded human decision. An organization
that agrees with these recommendations can reject or send back either mapping
for its own tenant through [Mapping review](../MAPPING_REVIEW.md). Do not change
an existing reviewed safeguard's definition without reviewing the affected
mappings again.

The packet was produced from the catalog before the decision with:

```bash
grc-lake frameworks review packet --framework soc2 \
  --control SOC2-A1.3 --control SOC2-C1.1 \
  --out docs/reviews/stability-review-packet.json
```

Both requirements are no longer pending, so the command now fails rather than
publishing an incomplete selection. Regression coverage checks the archived
packet against the catalog before the decision. It also sends synthetic passing
operational evidence through the pipeline against that catalog and verifies that
evidence alone never turns a proposed candidate into an attested requirement
pass.
