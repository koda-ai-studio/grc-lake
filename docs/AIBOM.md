# AI bill of materials

GRC Lake imports machine-readable AI inventory into the customer-controlled
lake and exports it without a hosted service.

```bash
grc-lake aibom import \
  --input model-bom.json \
  --lake build/lakehouse

grc-lake aibom export \
  --lake build/lakehouse \
  --format cyclonedx-1.7 \
  --out build/model-bom.cdx.json
```

The first command accepts CycloneDX 1.5–1.7 JSON or SPDX 3 JSON-LD and writes a
bounded canonical inventory to `aibom/inventory.json` under the lake. AI
governance inventory, API, CLI, and MCP reads then include those items.

Exports are inventory projections. Component content is derived only from the
stored inventory; each export gets a fresh document identifier and creation time.

- `cyclonedx-1.7` — `serialNumber` (`urn:uuid`), `metadata.timestamp` and
  `metadata.tools`, components, model cards (including `modelParameters` when
  the source supplied them, up to 64 KiB per model), package URLs, and licenses
- `spdx-3.0.1` — JSON-LD `@graph` with one `CreationInfo`, an `SpdxDocument`,
  `ai_AIPackage` for models, `dataset_DatasetPackage` for datasets (dataset type
  `noAssertion`), `software_Package` for applications and libraries, and declared
  licenses as `simplelicensing_LicenseExpression` elements linked by
  `hasDeclaredLicense` relationships

Inventory identifiers that are not `urn:` or `http(s)` IRIs become
document-scoped `urn:grc-lake:aibom:` identifiers in SPDX output. Both exports
validate against the official CycloneDX 1.7 and SPDX 3.0.1 JSON schemas; the
SPDX export does not carry model hyperparameters or training details.

Input is limited to 10 MiB. Unknown formats and documents without supported AI
model, dataset, application, or library components fail closed. GRC Lake stores
the source SHA-256 for provenance but does not upload the source document.

CycloneDX and SPDX remain the authorities for full schema/profile conformance:

- <https://cyclonedx.org/docs/1.7/json/>
- <https://spdx.github.io/spdx-spec/v3.0.1/model/AI/AI/>

## Model-card evidence

A model card describes intended use, limitations, and evaluation results. The
AI governance worklist reports whether a **signal about that documentation**
was collected for an inventory asset:

- **Model card not observed:** no positive signal for this asset in the loaded
  inventory. Ask the owner for the document and collect its evidence. The card
  may exist outside connected sources; this label is not a failed control.
- **Model card recorded:** a normalized event has JSON boolean
  `attributes.model_card: true`, or the CycloneDX import records a model card
  or a `model-card` external reference. A string such as `"false"` or `"true"`
  is not a boolean signal. Presence does not validate content or freshness.
- **Lineage recorded:** a lineage event exists. It does not establish that
  all training inputs, transformations, and deployments have been traced.

SPDX model classification alone does not establish documentation. The current
SPDX importer does not project model-card documentation relationships. Re-import
an SPDX document collected by an older version to replace its inferred card
flag; existing stored inventory is not automatically migrated.

Inventory identity is `(source_account_id, asset_id)` within one platform lake.
Identical asset IDs in different source accounts remain separate, including their
owners, controls, card signals, and evidence links. AIBOM imports currently have
no source-account binding. They can merge with an exact unscoped event identity,
but cannot supply documentation to a scoped source account. Events without a
card signal do not erase a matching imported signal. Names never establish a
match; ambiguous unscoped display names are omitted. These are accumulated
presence signals, not a current-state revocation or document-review ledger.
Repository AI-artifact counts are broader discovery signals and do not attach a
card to a model without an explicit asset binding.

The golden demo includes `model.lineage` and `ai.model_inventory` observations
without model-card signals. Its documentation gaps are deliberate synthetic inputs. Model-card
presence and lineage remain separate from evaluated framework controls and
human acceptance of the evidence.
