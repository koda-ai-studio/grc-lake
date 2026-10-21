# OSCAL export

`grc-lake oscal export` maps GRC Lake's own control model — the CCF
safeguards in `controls/safeguards.json` and the evaluated control posture in
a lake's `gold/control_posture.jsonl` — into NIST's
[OSCAL](https://pages.nist.gov/OSCAL/) (Open Security Controls Assessment
Language) layer models: **Component Definition**, **Catalog** (portable bundle), and **Assessment Results**.
OSCAL is the control/assessment interchange format auditor and GRC tooling
ecosystems consume; this export is read-only and one-way (GRC Lake's model
stays the source of truth, OSCAL is never imported back in).

This is an optional export format. JSONL and the `/api/v1` contract remain the
working data formats. XML/YAML OSCAL serializations, the OSCAL
Profile, System Security Plan, Assessment Plan, and POA&M layer models are not
implemented by this export.

## Try it locally

```bash
# Component Definition: one OSCAL component per CCF safeguard, with
# control-implementations for every reviewed framework mapping.
grc-lake oscal export --component-definition --out build/component-definition.json

# Assessment Results: one OSCAL finding per evaluated control in a lake.
grc-lake pipeline run --raw data/raw/security_events.jsonl --out build/oscal-demo-lake
grc-lake oscal export --assessment-results build/oscal-demo-lake \
  --out build/assessment-results.json
```

Both also stream to stdout when `--out` is omitted, and are available
read-only over the API:

```bash
curl -s http://127.0.0.1:8787/api/v1/oscal/component-definition | jq .
curl -s http://127.0.0.1:8787/api/v1/oscal/assessment-results | jq .
# Pin assessment-results to a recorded point-in-time snapshot instead of the
# current posture:
curl -s "http://127.0.0.1:8787/api/v1/oscal/assessment-results?snapshot_id=<id>" | jq .
```

## Component Definition: safeguard → implemented-requirement

Each CCF safeguard becomes one OSCAL `component` (type
`process-procedure`, since a safeguard is an operated control, not shipped
software). A safeguard's `satisfies` entries are grouped by `framework_id`
into one `control-implementation` per framework, each carrying the
`implemented-requirements` for that framework's requirements.

**Only `review_status: "reviewed"` mappings are emitted as
`implemented-requirements`.** A `proposed` (unreviewed) mapping is curation
backlog — a human has not confirmed the safeguard actually satisfies that
requirement — and OSCAL has no field to mark an implemented requirement as
unconfirmed. Emitting a proposed mapping would read to auditor tooling as an
asserted claim GRC Lake has not verified. This mirrors the same
`reviewed_only` distinction `safeguards_by_requirement()` already enforces for
attestable framework coverage (`src/security_lakehouse/safeguards.py`). A
safeguard whose only mappings are proposed still becomes a component (nothing
is silently dropped); it simply carries no `control-implementations`.

With `--lake` (CLI) or through the API, the export also includes mappings your
organization approved and leaves out any it rejected. Every implemented
requirement carries a `trustops-review-state` prop (`maintainer-reviewed` or
`org-reviewed`), and org-reviewed ones name the reviewer, decision time, and
decision id. See [Mapping review](MAPPING_REVIEW.md).

GRC Lake control ids are not always valid OSCAL tokens — HIPAA ids carry
parentheses (`HIPAA-164.308(a)(1)(ii)(A)`), which the OSCAL token grammar
forbids. The export sanitizes these into a valid token
(`HIPAA-164.308-a-1-ii-A`) and always records the original id verbatim in a
`trustops-control-id` prop, so nothing is lost to the sanitization.

## Assessment Results: control posture → finding

`--assessment-results <lake>` reads `gold/control_posture.jsonl` — the
per-control `pass`/`fail`/`stale`/`not_evaluated` rows the pipeline writes for
every generation — and emits one OSCAL `finding`, backed by one
`observation`, per control:

| GRC Lake `status` | OSCAL `target.status.state` | `reason` |
| ----------------- | --------------------------- | -------- |
| `pass`            | `satisfied`                 | `pass`   |
| `fail`            | `not-satisfied`             | `fail`   |
| `stale`           | `not-satisfied`             | `other`  |
| `not_evaluated`   | `not-satisfied`             | `other`  |

OSCAL only has two objective states. A control with stale evidence or no
active control definition is reported `not-satisfied`, never `satisfied` — an
auditor reading the export must never see an unconfirmed or unevaluated
control reported as passing. The original GRC Lake status is preserved
verbatim in a `trustops-status` prop on the finding.

`--snapshot <id>` reads frozen per-control detail from the snapshot's verified
generation, or from its embedded control rows. A snapshot without frozen detail
fails closed; current posture never substitutes for historical evidence.
Without `--snapshot`, the export reads the current pinned generation.

`import-ap.href` references the content-addressed catalog bundle
(`urn:grc-lake:catalog-bundle:<sha256>`) that was in force for the
assessment — GRC Lake has no separate OSCAL Assessment Plan document, so this
identifies the assessment basis but is not a resolvable OSCAL Assessment Plan.
Consumers requiring that model need an external assessment-plan integration.

## Validation

`tests/test_oscal.py` and `tests/test_oscal_bundle.py` validate the three models structurally against the vendored
OSCAL v1.2.3 JSON Schema in `controls/oscal/` (see
`controls/oscal/README.md` for provenance), and explicitly asserts that a
`proposed` safeguard mapping is never emitted as an
`implemented-requirement`.

Format reference: [OSCAL documentation](https://pages.nist.gov/OSCAL/) ·
[usnistgov/OSCAL](https://github.com/usnistgov/OSCAL) ·
[usnistgov/oscal-content](https://github.com/usnistgov/oscal-content) (example
documents this export's shape was checked against).

## Catalog and profile sources

Component implementation sources use pinned, machine-readable NIST OSCAL URLs
for SP 800-53 Rev. 5, the SP 800-53B Moderate profile, and SP 800-171 Rev. 3.
Implemented requirement IDs use the target source's native identifiers (including
case and prefixes); `trustops-control-id` retains the local identifier. The
legacy `fedramp-moderate` pack points to the NIST Moderate foundation profile;
it does not claim to include FedRAMP overlays. Frameworks without a configured
OSCAL source retain their official source link or local URN fallback.

## Portable CCF and framework bundle

Use the bundle when handing reviewed mappings to another tool or reviewer who
needs references that resolve offline:

```bash
grc-lake oscal export --component-bundle --out build/ccf-oscal.zip
# Include only this organization's mapping review decisions:
grc-lake oscal export --component-bundle --lake ./lake --out build/org-ccf-oscal.zip
```

Unzip it and open `component-definition.json` as the entrypoint. Its
`control-implementations[].source` values point to bundled `catalogs/*.json`.
Every `implemented-requirements[].control-id` resolves in the named catalog.
Native NIST identifiers are retained; every requirement also records the
original GRC Lake control ID. Ambiguous sanitized identifiers fail the export.

`manifest.json` identifies the entrypoint, hashes each document with SHA-256,
and separates **catalogued controls**, **unique requirements with reviewed
mappings**, and **reviewed mapping count** for each framework. Two safeguards
mapped to one requirement count as two mappings and one reviewed requirement.
Hashes detect file changes; they are not signatures or third-party attestations.
The CLI refuses to overwrite an existing bundle. It makes no network requests.

Catalogs include all requirements in the installed GRC Lake catalog, including
ones with proposed mappings only. These are **GRC Lake-authored projections**,
not official standards publications or reproductions of licensed standards.
Only eligible maintainer-reviewed or org-reviewed mappings appear as component
implementations; proposals, rejections, ambiguous mappings, and unknown targets
remain excluded. Organization review receipts are preserved when `--lake` is
supplied. The ZIP carries review identities; share it with the intended reviewer.

Catalog and mapping exports do not establish organization-specific control
implementation, assessed compliance, certification, or complete normative
coverage. This bundle does not contain lake evidence, assessment results, or an
Assessment Plan, and does not change the existing single-document API exports.
Validation covers OSCAL 1.2.3 schemas and offline reference integrity; it is not
qualification against a particular third-party GRC product.
