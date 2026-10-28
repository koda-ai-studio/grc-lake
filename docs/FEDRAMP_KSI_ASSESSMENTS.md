# FedRAMP KSI assessment subset

GRC Lake includes **2 of 46** indicators in the pinned FedRAMP KSI source:
`KSI-IAM-AAM` (Automating Account Management) and `KSI-IAM-APM` (Adopting
Passwordless Methods). Both mappings are **proposed**, with no recorded human
approval. The framework ID is `fedramp-ksi-2026`; it is separate from the existing
`fedramp-moderate` NIST Moderate foundation. Source ID coverage is not assessment
completeness, certification, readiness, or authorization.

## Source and applicability

The official [FedRAMP consolidated rules](https://github.com/FedRAMP/rules/blob/a89d78477ddea98dc57eca24f5007794c2b4eeb6/fedramp-consolidated-rules.json)
are pinned to commit `a89d78477ddea98dc57eca24f5007794c2b4eeb6`, dataset version
`2026.10.13.01`. The [assessment plan](../controls/fedramp_ksi_assessment_plan.json)
records the source and schema SHA-256 digests. Exact upstream bytes are retained
under `frameworks/packs/sources/fedramp-2026/`; the
[generated manifest](../frameworks/packs/data/fedramp_ksi_2026.json) contains the
selected statements, default artifact requirements, applicability context and
all 44 unseeded identifiers. Related NIST controls are source context only; they
do not create equivalence mappings.

An assessor must determine the applicable certification path, service class,
effective dates and Minimum Assessment Scope from the complete rules. The
manifest retains Class A, scope and automation context for that decision;
GRC Lake does not determine applicability automatically. The two selected
indicators do not constitute all Class A requirements.

## Evidence and failure modes

| Indicator     | Dedicated evidence type  | Required assessment and common gaps                                                                                                                                                                                              |
| ------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `KSI-IAM-AAM` | `ksi_iam_aam_assessment` | Account, role and group populations; lifecycle and privilege automation; exceptions and reconciled coverage. Orphan accounts, incomplete populations and unverified removal or privilege changes prevent a supported conclusion. |
| `KSI-IAM-APM` | `ksi_iam_apm_assessment` | Passwordless feasibility and deployment; where infeasible, strong passwords **and phishing-resistant MFA**; recovery, bypass and external identity-provider paths. A generic MFA-enabled flag cannot establish this indicator.   |

Each record must identify tenant and service scope, assessor, source revision,
assessment period, population reconciliation, evidence references, methods,
results and exceptions. The plan and review packet provide the detailed evidence
questions and expected failure modes. These are documentary obligations for the
assessor: the existing engine checks binding, asset and evidence type, status,
freshness and lineage; it does **not** automatically validate every documentary
field or prove the substance of an assessor's assertion. No new provider
collector or live qualification is included.

Use the existing evidence statuses honestly: a known failure is `open` or
`failed`; unknown applicability or unreadable evidence is `not_evaluated`;
an observation without a conclusion is `observed`. Missing records and stale
records remain distinct. Even a technical pass cannot attest either requirement
while its mapping is proposed. A human mapping decision and a human workpaper
decision are separate from evidence collection and control testing.

Persistent measures require their documented cycle, source revision, evidence
references and interruptions, plus verification of automation accuracy and
sufficiency and validation of operation. The included snapshot and sampled
period cannot establish persistent performance or continuous compliance.

## Try the draft handoff

From a repository checkout with `make uv-sync` completed:

```bash
uv run python tools/sync_fedramp_ksi.py --check
uv run grc-lake pipeline run --raw examples/fedramp-ksi/events.jsonl --out /tmp/grc-ksi-lake
uv run grc-lake assessment workpaper --lake /tmp/grc-ksi-lake \
  --plan examples/fedramp-ksi/plan.json --baseline examples/fedramp-ksi/baseline.json \
  --out /tmp/grc-ksi-workpaper
```

The synthetic fixture deliberately declares an unobserved service and lacks
complete indicator evidence across the declared population. Expect insufficient
operating evidence, population gaps, proposed framework mappings and an
unreviewed draft. Its fixed historical evidence can also become stale in a
current posture view. The workpaper uses the explicit period and cutoff in its
plan; those are different questions.

Retain the printed content SHA-256 independently and run the printed
`assessment verify-workpaper --dir ... --expected-content-sha256 ...` command
against the received bundle. This verifies bundle consistency and the retained
content hash. It does not authenticate an assessor or reviewer, approve the
workpaper, or remove its evidence gaps.

## Review and updates

The [bounded review packet](reviews/fedramp-ksi-packet.json) contains both source
requirements, safeguard rationale, evidence requirements, failure modes and
review-basis digests. All decision fields are blank. A qualified person must
check the pinned requirements and the applicability and evidence limitations
before recording a decision through the existing [mapping review](MAPPING_REVIEW.md)
workflow. Maintainer review is not independent auditor acceptance.

Reproduce the packet with:

```bash
uv run grc-lake frameworks review packet --framework fedramp-ksi-2026 \
  --out docs/reviews/fedramp-ksi-packet.json
```

Check upstream revisions at least every 30 days and after announced rule changes.
Reconcile changed versions, schema, applicability, source text and evidence
contracts in a new reviewed change. The offline replay rejects digest/version
drift, unknown or duplicate identifiers and changed existing contracts. It never
silently overwrites a human decision or promotes a proposal to reviewed.
