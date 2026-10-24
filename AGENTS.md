# Agent instructions

Guidance for coding agents (and humans) changing GRC Lake. [CONTRIBUTING.md](CONTRIBUTING.md)
is the full guide; this file lists what agents most often get wrong. Changes
prepared with an agent follow the same rules and need the same independent human
review as any other pull request.

## Set up and check

```bash
make uv-sync               # Python 3.11+, all extras from the frozen lockfile
make pre-commit-install    # pre-commit and Conventional Commit message hooks
make web-install           # console dependencies, Node 22+ (npm ci)
```

Run the checks for what you touched; CI runs all of them.

| Change                      | Command                                                                                      |
| --------------------------- | -------------------------------------------------------------------------------------------- |
| Python                      | `make lint format-check typecheck`, then targeted `python -m pytest -q tests/test_<name>.py` |
| Catalogs, fixtures, schemas | `make validate validate-json`                                                                |
| Console (`app/web/`)        | `make web-ci` and `npm --prefix app/web run lint`                                            |
| Docs and images             | `make validate-doc-images validate-brand`                                                    |
| Before pushing              | `pre-commit run --files <changed files>`                                                     |

Report the commands you actually ran in the pull request. Do not claim a check
passed unless you ran it.

## Evidence accuracy is the product

- Connectors are **read-only**. Never add write calls to a provider.
- Never turn missing, unreadable, or partial data into a pass. A failed or partial
  read is recorded as a collection gap and the run is marked partial; an empty
  success is a bug.
- Use the existing outcomes precisely: `open` asserts a failure; `not_evaluated`
  blocks a pass without asserting a failure; `observed` records evidence with no
  verdict. Pick the one the evidence actually supports.
- Bind evidence only to safeguards whose `asset_types` accept it, and keep control
  tags inside the bound safeguard's crosswalk. Framework results come from the
  reviewed crosswalk.
- **Proposed mappings are never attestable.** Agents may propose mappings; only a
  person who checked the requirement text can mark one `reviewed`
  ([mapping review](docs/MAPPING_REVIEW.md)).
- Do not edit `controls/safeguards.json` definitions casually: their digests are
  pinned to maintainer review receipts (`tests/test_ccf_maintainer_review_receipt.py`).
  Changing a definition requires a maintainer re-review.

## Connectors

Follow [Adding connectors](docs/ADDING_CONNECTORS.md) and copy a recent connector
(for example `connectors_lambda.py` or `connectors_jira.py` for REST APIs).

- Credentials only through secret references; never inline tokens, never log them.
- Fixed base URLs or an explicit host allowlist (no caller-supplied URLs); follow
  pagination links only on the same host; bounded page counts; handle 429 and
  `Retry-After`.
- Verify endpoints and fields against the vendor's official API docs, not memory.
- New connectors start at **Preview** with synthetic fixtures (no real tenant data)
  and a test through connector → `run_pipeline` → `gold/ccf_assessment.json`.
- Live runs are recorded as bounded receipts under `docs/qualification/live/`
  with no account, tenant, or project identifiers.

## Generated files: regenerate, don't hand-edit

| File                                       | Command                            |
| ------------------------------------------ | ---------------------------------- |
| README at-a-glance counts and header SVG   | `make readme-header`               |
| `docs/CONNECTOR_QUALIFICATION.md`          | `make connector-qualification-doc` |
| `docs/FRAMEWORK_COVERAGE.md`               | `make coverage-doc`                |
| `docs/api/openapi.v1.json` and API catalog | `make openapi-export`              |
| Framework packs                            | `make framework-packs`             |
| Demo screenshots                           | `make demo-screenshots-full`       |

## Code conventions

- Match the surrounding code; default to no comments unless the reason is not obvious.
- No `except ...: pass` without a comment explaining why (CodeQL flags it).
- Module-level names that exist only to be imported elsewhere belong in `__all__`.
- The console is a static Next.js export built with `next build --webpack`; keep
  demo-only code behind the `NEXT_PUBLIC_DEMO_SNAPSHOT` build flag.
- Do not regenerate `app/web/package-lock.json` with a different npm major version
  than CI; it rewrites unrelated fields.

## Public repository

Everything committed, and every issue and pull request, is public. Do not commit
credentials, real evidence, private audit notes, chat transcripts, or agent
handoff files. Describe GRC Lake on its own terms; do not name other products in
comparisons. Commit messages follow Conventional Commits, for example
`fix(connectors): keep Dependabot pagination on the same host`.
