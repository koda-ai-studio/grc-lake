"""Replica memory receipts measure simultaneous processes and clean their scratch lakes."""


def test_two_replicas_measure_aggregate_rss_and_clean_scratch(tmp_path):
    from tools.benchmark_graph_replicas import measure_replicas

    report = measure_replicas(tmp_path, rows=12, replicas=2, clients=2, seconds=0.2, timeout=60)
    assert report["correctness_ok"]
    assert report["peak_aggregate_rss_mib"] > 0
    assert report["max_simultaneous_processes"] == 2
    assert len(report["replicas"]) == 2
    assert all(r["correctness_ok"] for r in report["replicas"])
    assert not list(tmp_path.iterdir())


def test_replica_watchdog_retains_failed_measurement_and_cleans_scratch(tmp_path):
    from tools.benchmark_graph_replicas import measure_replicas

    report = measure_replicas(tmp_path, rows=12, replicas=2, clients=1, seconds=1, timeout=0.001)
    assert not report["correctness_ok"]
    assert report["stopped"] == "timeout"
    assert not list(tmp_path.iterdir())
