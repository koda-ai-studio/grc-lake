"""The console must not call the frozen pre-v1 surface.

`docs/API_V1_MIGRATION.md` promised this check ("CI: fail if `app/web` imports
`/api/` paths outside an allowlist") and it was never implemented, which is why
thirteen call sites in the API client and eight in-product agent recipes
survived the migration unnoticed.

Two shapes have to be checked, and missing the first is how this stayed hidden:

* `lib/api/client.ts` prefixes every request with ``BASE = "/api"``, so its
  calls read ``get("/violations")`` — there is no ``/api/`` in the source to
  grep for.
* Everywhere else (docs strings, the agent recipe catalog) writes the absolute
  path, ``"/api/violations"``.

`/api/healthz` and `/api/public/...` stay allowed: the first is the liveness
probe used by the container healthcheck and the ALB, the second is the
unauthenticated reviewer share.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_SRC = Path(__file__).resolve().parents[1] / "app" / "web" / "src"
CLIENT = WEB_SRC / "lib" / "api" / "client.ts"

ABSOLUTE_ALLOWED = ("/api/v1/", "/api/healthz", "/api/public/")

# Absolute paths written out in full, anywhere under src/.
ABSOLUTE_RE = re.compile(r"""["`](/api/[a-zA-Z0-9/{}$_.-]*)""")

# Calls inside client.ts, whose paths are relative to BASE = "/api".
RELATIVE_RE = re.compile(r"""(?:get|post|mutate|getAllV1)<[^(]*?\(\s*["`](/[a-zA-Z0-9/{}$_.-]*)""", re.S)
RELATIVE_ALLOWED = ("/v1/", "/v1", "/healthz")


def _absolute_offenders() -> list[str]:
    out: list[str] = []
    for path in sorted(WEB_SRC.rglob("*.ts*")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in ABSOLUTE_RE.finditer(line):
                api_path = match.group(1)
                # The bare prefix names no route; the live demo's replay layer
                # matches on it to answer every API request from its snapshot.
                if api_path in ("/api", "/api/") or api_path.startswith(ABSOLUTE_ALLOWED):
                    continue
                out.append(f"{path.relative_to(WEB_SRC)}:{lineno} {api_path}")
    return out


def _client_offenders() -> list[str]:
    source = CLIENT.read_text(encoding="utf-8")
    return [path for path in RELATIVE_RE.findall(source) if not path.startswith(RELATIVE_ALLOWED)]


def test_the_api_client_calls_only_versioned_routes() -> None:
    offenders = sorted(set(_client_offenders()))
    assert offenders == [], f"client.ts still calls pre-v1 routes: {offenders}"


def test_no_file_references_a_pre_v1_route() -> None:
    offenders = _absolute_offenders()
    assert offenders == [], "console references pre-v1 routes:\n  " + "\n  ".join(offenders)


def test_both_guards_actually_match_a_pre_v1_path() -> None:
    """A guard that cannot fail is not a guard.

    The relative form is the one that matters: it is what client.ts writes, and
    an /api/-only check passes over it silently.
    """
    assert RELATIVE_RE.search('  graph: () => get<ComplianceGraph>("/graph"),').group(1) == "/graph"
    assert not "/graph".startswith(RELATIVE_ALLOWED)

    assert ABSOLUTE_RE.search('endpoint: "/api/workflows",').group(1) == "/api/workflows"
    assert not "/api/workflows".startswith(ABSOLUTE_ALLOWED)
