## Summary

<!-- What changed and why. Link the issue: "Closes #123". -->

-

## Verification

<!-- Tick what you ran and paste anything notable. See CONTRIBUTING.md for which checks fit which change. -->

- [ ] `make lint format-check` and the touched tests (`python -m pytest -q tests/test_<name>.py`)
- [ ] `make smoke` (catalogs, fixtures, pipeline, API)
- [ ] `make web-ci` (console changes)
- [ ] `make validate-doc-images validate-brand` (docs images or brand assets)
- [ ] `make pre-commit-run`
- [ ] Screenshots in light and dark mode (console changes)

## Checklist

- [ ] Test-first: a test failed before this change and passes after (name it in the summary). See [AGENTS.md](../AGENTS.md#test-driven-changes).
- [ ] No new outbound destinations, telemetry, obfuscated code, or weakened security checks.
- [ ] Docs, API contract, and console agree with the change.
- [ ] No framework, connector, or control is described as covered or live-verified beyond what the catalog and tests support.
- [ ] No secrets, tokens, or real customer evidence in code, fixtures, logs, or screenshots.

## Human review

<!-- Before merge, obtain an independent human approval of the latest changes.
     CI and AI/bot reviews do not replace this approval. See CONTRIBUTING.md. -->
