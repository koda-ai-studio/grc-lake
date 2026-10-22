"""CLI composition for entity exports and append-only binding history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from security_lakehouse.entity_registry import entity_registry


def register(subparsers: Any) -> None:
    """Register the local, read-only export command without optional dependencies."""
    import json

    from security_lakehouse.io import read_json

    def export(args: Any) -> int:
        if args.revision is not None and not args.stored_bindings:
            raise ValueError("--revision requires --stored-bindings")
        if args.stored_bindings:
            from security_lakehouse.entity_history import stored_entity_registry

            result = stored_entity_registry(Path(args.lake), platform_tenant_id=args.tenant_id, revision=args.revision)
        else:
            bindings = read_json(args.bindings) if args.bindings else None
            result = entity_registry(Path(args.lake), platform_tenant_id=args.tenant_id, bindings=bindings)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    command = subparsers.add_parser("entities", help="explicit canonical entity registry (experimental)")
    actions = command.add_subparsers(dest="entities_command", required=True)
    export_parser = actions.add_parser("export", help="export observed identities and caller-asserted aliases as JSON")
    export_parser.add_argument("--lake", required=True, help="local lake already scoped to the platform tenant")
    export_parser.add_argument("--tenant-id", required=True, help="platform tenant namespace, not a source account")
    selection = export_parser.add_mutually_exclusive_group()
    selection.add_argument("--bindings", help="optional versioned JSON alias claims; never auto-inferred")
    selection.add_argument("--stored-bindings", action="store_true", help="use the verified persisted binding history")
    export_parser.add_argument(
        "--revision", type=int, help="export recorded binding evidence for a historical revision"
    )
    export_parser.set_defaults(func=export)

    from security_lakehouse.entity_history import register_history

    register_history(actions)
