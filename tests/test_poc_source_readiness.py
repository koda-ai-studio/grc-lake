from datetime import UTC, datetime, timedelta

import pytest

from security_lakehouse.poc_source_readiness import source_sync_readiness

NOW = datetime(2026, 11, 25, tzinfo=UTC)


def source(**sync):
    return {
        "state": "enabled",
        "is_implemented": True,
        "freshness_slo_minutes": 60,
        "last_sync": {"result": "ok", "occurred_at": NOW.isoformat(), "evidence_count": 3, **sync},
    }


@pytest.mark.parametrize(
    "sync,reason",
    [
        ({"result": "error"}, "successful sync"),
        ({"result": "skipped"}, "successful sync"),
        ({"evidence_count": 0}, "no evidence"),
        ({"evidence_count": None}, "no evidence"),
        ({"evidence_count": True}, "no evidence"),
        ({"metadata": {"partial": True}}, "partial"),
        ({"metadata": {"coverage_gaps": [{"reason": "redacted"}]}}, "partial"),
        ({"occurred_at": (NOW - timedelta(hours=2)).isoformat()}, "stale"),
        ({"occurred_at": (NOW + timedelta(minutes=1)).isoformat()}, "invalid sync times"),
        ({"occurred_at": "not-a-time"}, "invalid sync times"),
        ({"occurred_at": None}, "invalid sync times"),
    ],
)
def test_incomplete_source_cannot_borrow_another_sources_success(sync, reason):
    ready, detail = source_sync_readiness([source(), source(**sync)], evidence_count=100, now=NOW)
    assert not ready and reason in detail


def test_complete_sync_and_synthetic_boundary():
    ready, detail = source_sync_readiness([source()], evidence_count=3, now=NOW, synthetic=True)
    assert ready and "synthetic/demo" in detail
    assert "not provider qualification or a compliance verdict" in detail
    assert "live" not in detail


def test_disabled_sources_do_not_block_and_no_sources_are_not_ready():
    disabled = dict(source(result="error"), state="disabled")
    assert source_sync_readiness([source(), disabled], evidence_count=3, now=NOW)[0]
    assert not source_sync_readiness([disabled], evidence_count=3, now=NOW)[0]


def test_no_materialized_evidence_has_an_actionable_next_step():
    ready, detail = source_sync_readiness([source()], evidence_count=0, now=NOW)
    assert not ready and "materialize" in detail
