# Bounded SOC 2 second review

The [current packet](2026-11-02-soc2-second-review.json) selects three currently
reviewed mappings across the October 15 and October 25 maintainer receipts:
SOC2-A1.1, SOC2-C1.2 and SOC2-CC6.3. It preserves the existing reviewer and exact
semantic fingerprints. New decisions and rationales remain empty. Preparing or
merging this packet does not establish a second review or change coverage.

An independent reviewer should inspect the full requirement text, the selected
safeguard's operating contract, source references and applicability limits. For
each mapping, record the source/version, inspected fingerprint, decision,
rationale, reviewer, date and unresolved obligations through
[Mapping review](../MAPPING_REVIEW.md). Record independence from the original
reviewer separately; distinct names alone do not establish it.

Reproduce the packet from the current catalog:

```bash
grc-lake frameworks review packet --reviewed-only --framework soc2 \
  --control SOC2-A1.1 --control SOC2-C1.2 --control SOC2-CC6.3 \
  --out docs/reviews/2026-11-02-soc2-second-review.json
```

## Workpaper inspection

Generate the existing synthetic access/change workpaper matrix in a new local
directory:

```bash
uv run --frozen python tools/qualify_control_workflow.py --out /tmp/soc2-workpaper-review
```

Inspect each case's `events.jsonl`, `plan.json`, `baseline.json`, exported
`workpaper/workpaper.json`, `workpaper/index.html` and report fingerprints.
Prioritize `complete_samples`, `observed_failure`, `partial_collection`,
`missing_window` and `stale_design` for both safeguards. Check that a sampled
pass does not conceal an incomplete population, missing period, stale design,
proposed mapping or unresolved human conclusion. Verify the pinned export, not
just its internal hash consistency. The matrix is synthetic application evidence;
it does not establish live operating effectiveness.

Record workpaper findings and conclusions separately from mapping decisions and
code approval. An automated check is not the independent reviewer.

## Next SOC 2 backlog

After use-discovered defects, prioritize [recovery testing and confidential-data
protection](RECOVERY_CONFIDENTIALITY.md): SOC2-A1.3 and SOC2-C1.1 remain proposed.
A backup result does not demonstrate a recovery exercise; an inventory does not
demonstrate protection. Resolve their scope and missing obligations before
expanding ISO mappings or provider coverage. Existing safeguard definitions are
bound to maintainer receipts and require re-review if changed.
