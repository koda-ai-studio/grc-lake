# ASCII system map

```text
Read-only connectors or existing-lake readers
                    |
                    v
        Raw observations + collection receipts
                    |
                    v
       Validate / hash / normalize evidence
       Source account + asset + evidence identity
                    |
                    v
       Versioned controls + reviewed CCF mappings
       Deterministic evaluation + freshness
                    |
                    v
       Stage / seal / publish a generation
       Failure preserves previous committed view
                    |
          +---------+------------------+
          |                            |
          v                            v
  Pinned assessment reads      Optional warehouse export
  Console / API / CLI / MCP    Separate outcome after commit
          |
          v
  Scoped plan + population reconciliation
  Human review + frozen workpaper / snapshot
          |
          v
  Verify export / chain / retained checkpoint
```

Authenticated platform identity selects the tenant lake before hosted reads or
writes. Source-account identity remains evidence provenance. Human review and
agent proposals do not override deterministic results. Filesystem mode has one
writable replica; distributed mode coordinates publication in PostgreSQL and
stores evidence objects in S3. Optional warehouse exports are separate from both.

See [architecture](../ARCHITECTURE.md), [data model](../DATA_MODEL.md),
[authority](auth-identity.md), and [warehouse integration](dual-lakehouse.md).
