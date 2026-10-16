"""Opt-in guard: pytest -p tools.pytest_strict_imports [--allow-import-skip=MODULE].

A ``pytest.importorskip`` skip becomes a failure, so an environment that is
meant to install every optional extra cannot pass by silently skipping the
tests that need them. Modules named by ``--allow-import-skip`` (and their
submodules) may still skip; ordinary ``pytest.skip`` calls are unaffected.
"""

from __future__ import annotations

import re
from collections.abc import Generator

import pytest

_IMPORT_SKIP = re.compile(r"could not import '([^']+)'")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--allow-import-skip",
        action="append",
        default=[],
        metavar="MODULE",
        help="Top-level module whose importorskip may still skip",
    )


def _enforce(config: pytest.Config, report: pytest.CollectReport | pytest.TestReport) -> None:
    if not report.skipped:
        return
    longrepr = report.longrepr
    message = longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)
    match = _IMPORT_SKIP.search(message)
    if match is None or match.group(1).split(".", 1)[0] in config.getoption("--allow-import-skip"):
        return
    report.outcome = "failed"
    report.longrepr = f"optional dependency missing under tools.pytest_strict_imports: {message}"


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(
    collector: pytest.Collector,
) -> Generator[None, pytest.CollectReport, pytest.CollectReport]:
    report = yield
    _enforce(collector.config, report)
    return report


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    _enforce(item.config, report)
    return report
