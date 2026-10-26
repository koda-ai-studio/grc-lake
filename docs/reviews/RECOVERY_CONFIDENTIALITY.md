# Recovery and confidentiality: focused review

The [current candidate packet](stability-review-packet.json) contains two pending
SOC 2 requirements with exact operating contracts and review fingerprints. It
records no human decisions and grants no additional reviewed coverage. The
existing [SOC 2 review queue](SOC2_ISO_REVIEW.md#soc2-review-001) supplies source
locators and questions; vendor guidance is not the full normative requirement.

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

## Record an actual decision

These are engineering review recommendations, not human mapping decisions.
Keep both mappings proposed until an eligible person checks the full requirement
text and the exact candidate contract. Record the source/version, inspected
fingerprint, decision, rationale, reviewer and limits through
[Mapping review](../MAPPING_REVIEW.md). Do not treat approval of the code PR as
approval of these mappings. Do not change an existing reviewed safeguard's
definition without reviewing the affected mappings again.

The focused packet can be reproduced from the current catalog:

```bash
grc-lake frameworks review packet --framework soc2 \
  --control SOC2-A1.3 --control SOC2-C1.1 \
  --out docs/reviews/stability-review-packet.json
```

If a requested requirement is no longer pending, the command fails rather than
silently publishing an incomplete selection. Refresh the selection and review
state deliberately. Regression coverage also sends synthetic passing operational
evidence through the pipeline and verifies that neither proposed candidate
becomes an attested requirement pass.
