"""The console reads pass, fail and stale evidence exactly as the evaluator does."""

from __future__ import annotations

import re
from pathlib import Path

from security_lakehouse.event_status import _ALIASES, FAIL_STATUSES, PASS_STATUSES
from security_lakehouse.evidence_freshness import STALE_STATUSES

WEB = Path(__file__).parents[1] / "app/web/src"
MODULE = WEB / "lib/evidence-status.ts"


def _set(source: str, name: str) -> set[str]:
    match = re.search(rf"export const {name} = new Set\(\[(.*?)\]\)", source, re.S)
    assert match, name
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _with_aliases(canonical: frozenset[str]) -> set[str]:
    return set(canonical) | {alias for alias, target in _ALIASES.items() if target in canonical}


def test_console_status_sets_match_the_evaluator() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert _set(source, "PASSING_STATUSES") == _with_aliases(PASS_STATUSES)
    assert _set(source, "FAILING_STATUSES") == _with_aliases(FAIL_STATUSES)
    assert _set(source, "STALE_FRESHNESS") == STALE_STATUSES


def test_graph_code_declares_no_private_status_lists() -> None:
    for path in (WEB / "lib/graph-evidence.ts", WEB / "components/graph/GraphCanvas.tsx"):
        source = path.read_text(encoding="utf-8")
        assert '"expired"' not in source, path
        assert '"noncompliant"' not in source, path
        assert '"compliant"' not in source, path
