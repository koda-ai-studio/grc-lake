"""Read one authorized KnowBe4 list using cursors only; emit a data-minimized receipt."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from security_lakehouse.connectors_knowbe4 import KNOWBE4_REGIONS, KnowBe4Client, _link_cursor
from security_lakehouse.secret_refs import resolve_secret_ref

COLLECTIONS = {"users": "users", "enrollments": "training_enrollments", "phishing": "phishing_tests"}


def qualify(region, token, collection, *, expected_count, min_interval=1.25, max_pages=20):
    pages = []

    class Client(KnowBe4Client):
        def _fetch(self, path, query):
            payload, headers = super()._fetch(path, query)
            pages.append({"rows": len(payload), "link_next_cursor_present": _link_cursor(headers) is not None})
            return payload, headers

    result = {
        "schema_version": "grc.knowbe4_cursor_qualification.v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "region": region,
        "collection": collection,
        "expected_rows": expected_count,
        "max_pages": max_pages,
        "legacy_fallback": False,
        "pages": pages,
        "scope": "One list and one observation; expected count must come from an independent account baseline.",
    }
    try:
        client = Client(region, token=token, min_interval=min_interval, allow_legacy_paging=False, max_pages=max_pages)
        rows = getattr(client, COLLECTIONS[collection])()
        result["rows"] = len(rows)
        result["status"] = (
            "qualified" if len(rows) == expected_count and len(rows) > 500 and len(pages) > 1 else "not_qualified"
        )
    except (OSError, ValueError, RuntimeError) as exc:
        # Provider exceptions may contain URLs, cursors or response bodies.
        result.update(status="incomplete", error_type=type(exc).__name__)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=KNOWBE4_REGIONS, required=True)
    parser.add_argument("--collection", choices=COLLECTIONS, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--credential-ref", default="KNOWBE4_API_TOKEN")
    parser.add_argument("--max-pages", type=int, choices=range(2, 101), default=20)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.expected_count <= 500:
        parser.error("qualification requires an independent baseline of more than 500 records")
    if args.out.exists():
        parser.error("choose a new receipt path; prior attempts must be retained")
    try:
        token = resolve_secret_ref(args.credential_ref, dict(os.environ))
    except (OSError, ValueError, RuntimeError):
        parser.error("credential reference could not be resolved")
    if not token:
        parser.error("credential reference could not be resolved")
    result = qualify(args.region, token, args.collection, expected_count=args.expected_count, max_pages=args.max_pages)
    root = Path(__file__).resolve().parents[1]
    result["revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    result["source_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "pages": len(result["pages"])}))
    return 0 if result["status"] == "qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
