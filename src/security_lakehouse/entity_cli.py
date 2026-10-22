"""CLI wiring for entity projections and operational history; domain modules stay acyclic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from security_lakehouse.entity_history import binding_history, record_bindings, stored_entity_registry
from security_lakehouse.entity_registry import entity_registry


def register(subparsers: Any) -> None:
    """Register the local, read-only export command without optional dependencies."""
    from security_lakehouse.io import read_json

    def export(args: Any) -> int:
        if args.revision is not None and not args.stored_bindings:
            raise ValueError("--revision requires --stored-bindings")
        if args.stored_bindings:
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

    register_history(actions)


def register_history(actions: Any) -> None:
    from security_lakehouse.io import read_json

    def record(args: Any) -> int:
        result = record_bindings(
            Path(args.lake),
            platform_tenant_id=args.tenant_id,
            bindings=read_json(args.bindings),
            actor=args.actor,
            reason=args.reason,
            expected_revision=args.expected_revision,
            request_id=args.request_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    def history(args: Any) -> int:
        print(json.dumps(binding_history(Path(args.lake), platform_tenant_id=args.tenant_id), indent=2, sort_keys=True))
        return 0

    for name, handler in (("record", record), ("history", history)):
        command = actions.add_parser(
            name, help="record a complete binding revision" if name == "record" else "verify and list binding revisions"
        )
        command.add_argument("--lake", required=True)
        command.add_argument("--tenant-id", required=True)
        command.set_defaults(func=handler)
        if name == "record":
            command.add_argument(
                "--bindings", required=True, help="complete replacement manifest; omitted aliases are revoked"
            )
            command.add_argument("--actor", required=True, help="caller identity; not authenticated approval")
            command.add_argument("--reason", required=True)
            command.add_argument("--expected-revision", required=True, type=int, help="0 for the first revision")
            command.add_argument("--request-id", required=True, help="unique retry key for this exact request")
