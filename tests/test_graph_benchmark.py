"""The measurement harness must enforce correctness rather than just time reads."""

import pytest
from tools.benchmark_investigation import run_workload, validate_response


def test_dangling_edges_and_foreign_tenant_data_fail_measurement():
    with pytest.raises(ValueError, match="dangling"):
        validate_response({"nodes": [], "edges": [{"source": "x", "target": "y"}]}, "tenant-0", 150)
    with pytest.raises(ValueError, match="tenant"):
        validate_response(
            {"nodes": [{"id": "x", "source_account_id": "tenant-1-account-a"}], "edges": []}, "tenant-0", 150
        )


@pytest.mark.parametrize("frozen_catalogs", [False, True])
def test_small_workload_checks_generation_isolation_and_records_all_queries(tmp_path, frozen_catalogs):
    report = run_workload(tmp_path, rows=12, tenants=2, concurrency=2, repeats=1, frozen_catalogs=frozen_catalogs)
    assert report["correctness_ok"]
    assert report["checks"] == {
        "source_account_isolation": True,
        "exact_bindings": True,
        "duplicate_records": True,
        "pinned_concurrent_publication": True,
        "stale_version_rejected": True,
        "overlay_version_rejected": True,
        "root_pagination": True,
        "account_collision_isolation": True,
        "control_pagination": True,
    }
    assert {r["query"] for r in report["reads"]} >= {
        "first",
        "repeat",
        "depth1",
        "depth3",
        "layers",
        "search",
        "roots_page2",
        "concurrent",
    }
    assert len([r for r in report["reads"] if r["query"] == "concurrent"]) == 4
    assert report["model_counts"]["evidence_type"] == 12
    assert report["input_rows_including_duplicates"] == 13
    assert report["retained_bytes"] > 0


def test_watchdog_retains_stop_and_removes_worker_scratch(tmp_path):
    from types import SimpleNamespace

    from tools.benchmark_investigation import attempt

    args = SimpleNamespace(scratch=tmp_path, min_free_gib=1, tenants=1, repeats=1, timeout=0.001, max_rss_mib=1024)
    result = attempt(args, 1000, 1)
    assert result["stopped"] == "timeout"
    assert not list(tmp_path.iterdir())
    # Host contention is retained with every attempt, including stopped ones.
    assert len(result["load_average_before"]) == 3
    assert len(result["load_average_after"]) == 3


def test_disk_floor_refuses_start(tmp_path):
    from types import SimpleNamespace

    from tools.benchmark_investigation import attempt

    args = SimpleNamespace(scratch=tmp_path, min_free_gib=10**9)
    assert attempt(args, 1000, 1)["stopped"] == "disk_floor_before_start"
    assert not list(tmp_path.iterdir())


def test_seeded_fixture_is_deterministic_and_uses_catalog_controls():
    from tools.benchmark_investigation import fixture_rows

    from security_lakehouse.catalog import control_catalog_view

    first = list(fixture_rows(200, "tenant-0", seed=7))
    assert first == list(fixture_rows(200, "tenant-0", seed=7))
    assert first != list(fixture_rows(200, "tenant-0", seed=8))
    # The seed fixes topology; tenants differ only in record identity.
    other = list(fixture_rows(200, "tenant-1", seed=7))
    assert [r["control_ids"] for r in first] == [r["control_ids"] for r in other]
    assert {r["raw_sha256"] for r in first}.isdisjoint(r["raw_sha256"] for r in other)
    catalog = control_catalog_view()
    used = {c for r in first for c in r["control_ids"]}
    assert len(used) > 2 and used <= set(catalog)
    assert len({r["asset_type"] for r in first}) > 1
    # No seed keeps the original uniform shape for comparison with old receipts.
    legacy = list(fixture_rows(4, "tenant-0"))
    assert [r["control_ids"] for r in legacy] == [["SOC2-CC6.1"], ["SOC2-CC7.2"]] * 2


def test_platform_tenants_share_a_colliding_source_account():
    from tools.benchmark_investigation import COLLIDING_ACCOUNT, fixture_rows

    zero = list(fixture_rows(4, "tenant-0"))
    one = list(fixture_rows(4, "tenant-1"))
    assert zero[0]["tenant_id"] == one[0]["tenant_id"] == COLLIDING_ACCOUNT
    assert zero[0]["asset_id"] == one[0]["asset_id"]
    assert zero[1]["tenant_id"] == "tenant-0-account-b" != one[1]["tenant_id"]


def test_foreign_evidence_under_a_colliding_account_fails_measurement():
    from tools.benchmark_investigation import COLLIDING_ACCOUNT, expected_evidence_ids

    own = expected_evidence_ids(4, "tenant-0")
    foreign = sorted(expected_evidence_ids(4, "tenant-1"))[0]
    node = {"id": foreign, "kind": "evidence_type", "source_account_id": COLLIDING_ACCOUNT}
    # The account ID alone cannot tell the tenants apart; record identity does.
    validate_response({"nodes": [{**node, "id": sorted(own)[0]}], "edges": []}, "tenant-0", 150, evidence_ids=own)
    with pytest.raises(ValueError, match="tenant isolation"):
        validate_response({"nodes": [node], "edges": []}, "tenant-0", 150, evidence_ids=own)


def test_control_paging_root_is_found_when_evidence_exceeds_the_response_cap(tmp_path):
    from tools.benchmark_investigation import control_page_query, make_generation

    from security_lakehouse.generations import publish_generation

    lake = tmp_path / "tenant-0"
    # 400 records put far more than 150 evidence nodes next to SOC2-CC6.1.
    publish_generation(lake, make_generation(lake, 400, "tenant-0"))
    query = control_page_query(lake)
    assert query["root"].startswith("safeguard:") and query["framework"]


def test_seeded_workload_measures_pagination_search_and_throughput(tmp_path):
    report = run_workload(tmp_path, rows=12, tenants=2, concurrency=2, repeats=1, seed=3)
    assert report["seed"] == 3
    assert report["checks"]["account_collision_isolation"]
    assert report["checks"]["control_pagination"]
    queries = {r["query"] for r in report["reads"]}
    assert {"search_miss", "controls_page1", "controls_page2"} <= queries
    miss = next(r for r in report["reads"] if r["query"] == "search_miss")
    assert miss["matching_nodes"] == 0
    burst = report["concurrent_burst"]
    assert burst["reads"] == 4 and burst["wall_seconds"] > 0
    assert burst["reads_per_second"] == pytest.approx(4 / burst["wall_seconds"])
    assert report["retained_bytes"] > 0
