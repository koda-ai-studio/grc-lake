# Control design and period testing

`assessment test-plan` evaluates a versioned test plan against one verified sealed
generation. Plans name the operated CCF safeguard, activity, owner, system,
frequency, procedure, sample size, sampling rationale, design evidence IDs, and
closed assessment period. Requirement mappings come from the generation's CCF
catalog, with their review states, rather than from claims in the plan.

```sh
grc-lake pipeline run --raw examples/control-assurance/events.jsonl --out build/assurance-demo
grc-lake assessment test-plan --lake build/assurance-demo --plan examples/control-assurance/plan.json
```

The fixture uses five controls: privileged access, production changes, audit
logging, encryption, and AI model inventory. All records are synthetic. Change
management has a failing observation; AI inventory has a missing daily window.
The other three have passing samples. These are demonstrations, not operational
claims about this repository or a real organization.

## What the conclusions mean

- **Design documented:** each declared design record exists, explicitly binds to
  the safeguard, reports a passing outcome, predates the test period by at most
  366 days, and was collected by the assessment cutoff. A reviewer must still
  assess whether the design addresses the risk and inspect the underlying source.
- **Sample pass:** each expected asset has enough valid observations in every
  cadence window for each required evidence type, and there are no observed deviations or unknown outcomes in the
  period. Sample ranking uses SHA-256 over the plan digest and event ID, making
  selection reproducible. All observed failures remain visible even if unselected.
- **Sample fail:** at least one observed in-period outcome failed.
- **Insufficient evidence:** missing windows, unbound observations, missing design
  documents, unknown outcomes, or invalid collection times prevent support.

Standalone test plans use observed period assets. Workpapers also include the
declared inventory, independently of whether its evidence binds to the tested
safeguard. A declared asset is excluded only when evidence collected by the cutoff
establishes one asset type recognized by the pinned catalog that is incompatible
with the safeguard. Missing, unrecognized, or ambiguous type evidence cannot
establish an exclusion. Such assets remain expected and missing bound samples
appear as per-asset, per-window gaps. Source account and asset ID jointly identify
the asset; evidence in another account cannot fill its gaps. Population
reconciliation remains a separate claim and never substitutes for control samples.

Windows are half-open `[start, end)`. Design evidence cannot also serve as
operating evidence. Assessment periods must be closed, no longer than 366 days,
and not in the future. Plans are bounded to 50 controls, 100 samples per window,
and 50,000 asset/window cells per control. The implementation indexes events once;
these bounds are protective limits, not measured production capacity.

Every conclusion remains `pending_human_review`. A machine-generated workpaper is
not an audit opinion. Observed-population sampling does not establish inventory
completeness, statistical confidence, or continuous effectiveness between
observations. The plan and results carry canonical hashes and the generation
identity so reviewers can reproduce the selection and inspect evidence lineage.

## Evidence eligibility (output v2)

Workpaper output `trustops.control_assurance.v2` requires available evidence for
design support, assessment context and operating samples. An internal bronze
reference remains valid; a public URL is not required. Explicitly unavailable
references cannot satisfy a design requirement or period window. Eligible
operating samples must also match the asset type, timing and pass/fail status
contract; inventory-only `observed` events do not supply operating verdicts.
Ineligible samples remain gaps rather than silently becoming passing results.

## Separate identity evidence obligations

A test plan control can declare `required_evidence_types`, for example:

```json
{
  "required_evidence_types": [
    "identity.mfa",
    "identity.privileged_access",
    "identity.access_review"
  ],
  "sample_per_window": 1
}
```

These are distinct assessor evidence types in the example, not automatic claims
that an MFA enrollment event proves policy enforcement, privileged authorization,
or completion of an access review. Record each actual test outcome and reference
its evidence. A review decision to remove access also requires follow-up evidence
that access was removed before claiming successful remediation.

The plan's types are added to the pinned safeguard's required types; a plan cannot
remove catalog obligations. For each source tenant, asset and cadence window,
`sample_per_window` applies separately to every required type. Missing types are
listed on the gap record. Selection is deterministic within each type; a record
that explicitly supplies several types is retained once. Samples include their
normalized evidence types and source hashes. All observed failures and invalid
outcomes still count, including records outside the selected samples.

```sh
grc-lake pipeline run --raw examples/control-assurance/identity-events.jsonl --out build/identity-assurance
grc-lake assessment test-plan --lake build/identity-assurance --plan examples/control-assurance/identity-plan.json
```

This synthetic example has two principals and two daily windows. One principal
is missing the second access-review observation. Its workpaper must report
`insufficient_evidence`; the other principal's complete records cannot fill that
gap. Supplying the missing observation as `observed` or collecting it after the
cutoff still does not satisfy the window.

Required types are bounded to 20 distinct nonempty names. Omitting the plan field
preserves catalog requirements; if neither declares types, sampling uses the
existing per-asset/window count. Types can arrive from different evidence sources
for the same asset, but not from another asset or source tenant. Current posture,
control-test API responses used by the console, and CCF requirement assessment
apply the same asset boundary when checking required evidence freshness. Frozen
snapshots and their OSCAL results preserve the original incomplete assessment
after later evidence completes the current one.
