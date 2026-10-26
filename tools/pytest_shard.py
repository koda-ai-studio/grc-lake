"""Opt-in, deterministic module sharding: pytest -p tools.pytest_shard --ci-shard=1/4.

Balance by recorded module run time when ``--ci-shard-durations`` names a JSON
map of module path to seconds; modules missing from it are estimated from their
collected test count at the recorded average per-test time. Without the file,
balance by collected test count. Modules are never split across runners, new
tests participate automatically, ordinary pytest runs are unchanged, and empty
shards retain pytest's nonzero exit status.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--ci-shard", help="One-based shard index/count, for example 1/4")
    parser.addoption("--ci-shard-durations", help="JSON map of test module path to recorded seconds")


def _shard(config: pytest.Config) -> tuple[int, int] | None:
    value = config.getoption("--ci-shard")
    if value is None:
        return None
    try:
        index, count = map(int, value.split("/"))
        if not 1 <= index <= count:
            raise ValueError
    except ValueError as exc:
        raise pytest.UsageError("--ci-shard must be index/count with 1 <= index <= count") from exc
    return index - 1, count


def pytest_configure(config: pytest.Config) -> None:
    _shard(config)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    shard = _shard(config)
    if shard is None:
        return
    index, count = shard
    modules: dict[str, list[pytest.Item]] = defaultdict(list)
    for item in items:
        modules[item.nodeid.split("::", 1)[0]].append(item)
    weights = _module_weights(config, modules)
    loads = [0.0] * count
    owners: dict[str, int] = {}
    for module in sorted(modules, key=lambda name: (-weights[name], name)):
        owner = min(range(count), key=lambda candidate: (loads[candidate], candidate))
        owners[module] = owner
        loads[owner] += weights[module]
    selected, deselected = [], []
    for item in items:
        target = selected if owners[item.nodeid.split("::", 1)[0]] == index else deselected
        target.append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)


def _module_weights(config: pytest.Config, modules: dict[str, list[pytest.Item]]) -> dict[str, float]:
    counts = {name: float(len(tests)) for name, tests in modules.items()}
    path = config.getoption("--ci-shard-durations")
    if not path:
        return counts
    recorded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(recorded, dict) or not all(
        isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds >= 0
        for seconds in recorded.values()
    ):
        raise pytest.UsageError("--ci-shard-durations must map module paths to non-negative seconds")
    known = [name for name in modules if name in recorded]
    tests = sum(counts[name] for name in known)
    per_test = sum(recorded[name] for name in known) / tests if tests else 1.0
    return {name: float(recorded[name]) if name in recorded else counts[name] * per_test for name in modules}
