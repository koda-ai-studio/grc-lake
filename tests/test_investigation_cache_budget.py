"""Cache retention and concurrent failure behavior have independent bounds."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from security_lakehouse import investigation_cache as cache


def model(label="one"):
    from security_lakehouse.investigation_index import build_indexes

    nodes = {"node": {"id": "node", "kind": "asset", "label": label}}
    return nodes, {}, {}, label, build_indexes(nodes, {}, lambda: None)


def test_lru_byte_count_entry_count_and_same_lake_replacement():
    value = model()
    size = cache.model_size(value, 10000, lambda: None)
    store = cache.ModelCache(max_bytes=size * 2, max_entries=3)
    calls = []

    def read(lake, version="v1"):
        def build():
            calls.append((lake, version))
            return value

        return store.get_or_build((lake, version), build, lambda: True, lambda: None)

    read("a")
    read("b")
    read("a")
    read("c")
    assert list(store._entries) == [("a", "v1"), ("c", "v1")]
    assert store._bytes == size * 2
    read("a", "v2")
    assert list(store._entries) == [("c", "v1"), ("a", "v2")]
    read("b")
    assert len(calls) == 5
    store.max_entries = 1
    read("d")
    assert list(store._entries) == [("d", "v1")]
    assert store._bytes == size


def test_oversized_model_is_returned_but_not_retained():
    store = cache.ModelCache(max_bytes=1)
    value = model()
    assert store.get_or_build(("a", "v"), lambda: value, lambda: True, lambda: None) == value
    assert not store._entries and not store._building and store._bytes == 0


def test_expiry_rebuilds_without_requiring_background_threads(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cache, "monotonic", lambda: clock[0])
    store = cache.ModelCache(ttl=60)
    builds = []

    def build():
        builds.append(1)
        return model()

    for instant in (0, 30, 61):
        clock[0] = instant
        store.get_or_build(("a", "v"), build, lambda: True, lambda: None)
    assert len(builds) == 2


def test_canceled_waiter_does_not_abort_leader():
    store = cache.ModelCache()
    entered, release, canceled = Event(), Event(), Event()

    def build():
        entered.set()
        assert release.wait(5)
        return model()

    checks = []

    def check():
        checks.append(1)
        if len(checks) > 1:
            canceled.set()
            raise RuntimeError("waiter disconnected")

    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(store.get_or_build, ("a", "v"), build, lambda: True, lambda: None)
        assert entered.wait(5)
        waiter = pool.submit(store.get_or_build, ("a", "v"), build, lambda: True, check)
        assert canceled.wait(5)
        with pytest.raises(RuntimeError, match="waiter disconnected"):
            waiter.result()
        release.set()
        assert leader.result() == model()
    assert not store._building and len(store._entries) == 1


def test_failed_leader_releases_waiter_to_retry():
    store = cache.ModelCache()
    entered, release, waiting = Event(), Event(), Event()
    calls = []

    def build():
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
            raise RuntimeError("leader disconnected")
        return model()

    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(store.get_or_build, ("a", "v"), build, lambda: True, lambda: None)
        assert entered.wait(5)
        waiter = pool.submit(store.get_or_build, ("a", "v"), build, lambda: True, waiting.set)
        assert waiting.wait(5)
        release.set()
        with pytest.raises(RuntimeError, match="leader disconnected"):
            leader.result()
        assert waiter.result() == model()
    assert len(calls) == 2 and not store._building and len(store._entries) == 1


def test_canceled_size_accounting_does_not_publish():
    store = cache.ModelCache()
    built = False

    def build():
        nonlocal built
        built = True
        return model()

    def check():
        if built:
            raise RuntimeError("deadline")

    with pytest.raises(RuntimeError, match="deadline"):
        store.get_or_build(("a", "v"), build, lambda: True, check)
    assert not store._entries and not store._building


def test_oversized_build_is_shared_with_existing_waiters_but_not_retained():
    store = cache.ModelCache(max_bytes=1)
    entered, release, waiting = Event(), Event(), Event()
    calls = []
    checkpoints = []

    def build():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return model()

    def waiter_check():
        checkpoints.append(1)
        if len(checkpoints) > 1:
            waiting.set()

    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(store.get_or_build, ("a", "v"), build, lambda: True, lambda: None)
        assert entered.wait(5)
        waiter = pool.submit(store.get_or_build, ("a", "v"), build, lambda: True, waiter_check)
        assert waiting.wait(5)
        release.set()
        assert leader.result() is waiter.result()
    assert len(calls) == 1
    assert not store._entries and not store._building and store._bytes == 0
