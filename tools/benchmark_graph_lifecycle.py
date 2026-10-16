"""Loopback fault probes, reported separately from natural graph latency."""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx

from security_lakehouse import investigation_graph as graph
from security_lakehouse.graph_admission import GraphBuildAborted

ROUTE = "/api/v1/graph/investigation"


def wait_for_release(app, timeout=5):
    deadline = time.monotonic() + timeout
    while app.state.graph_build_slots.active:
        if time.monotonic() >= deadline:
            raise ValueError("graph slot was not released after lifecycle probe")
        time.sleep(0.01)


def run_lifecycle_probes(app, url, credential, *, client_timeout, graph_timeout):
    """Use the real route/token and builder checkpoint with explicit injected holds.

    The deadline hold proves the configured timer, not natural build duration.
    The disconnect hold synchronizes socket closure with a running checkpoint;
    it avoids confusing a fast completed request with a cancelled one.
    Call only in a dedicated benchmark worker with no concurrent normal reads.
    """
    if graph_timeout is None or client_timeout <= graph_timeout:
        raise ValueError("lifecycle probes require a finite server deadline below the client timeout")
    headers = {"Authorization": "Bearer " + credential}
    original = graph.investigation_graph

    def held_until_deadline(lake, *, checkpoint, **kwargs):
        stop = time.monotonic() + graph_timeout + 5
        while time.monotonic() < stop:
            checkpoint()
            time.sleep(0.01)
        raise ValueError("server deadline was not enforced")

    started = time.perf_counter()
    with patch.object(graph, "investigation_graph", held_until_deadline):
        response = httpx.get(url + ROUTE, headers=headers, timeout=client_timeout, trust_env=False)
    elapsed = time.perf_counter() - started
    if response.status_code != 503 or response.json()["errors"][0]["code"] != "graph_build_timeout":
        raise ValueError("server deadline did not return graph_build_timeout")
    wait_for_release(app)
    deadline_receipt = {
        "injection": "cooperative hold before graph construction",
        "configured_seconds": graph_timeout,
        "seconds": elapsed,
        "http_status": response.status_code,
        "error_code": "graph_build_timeout",
    }

    entered = threading.Event()
    finished = threading.Event()
    outcome = {"checkpoints": 0}

    def observed_build(lake, *, checkpoint, **kwargs):
        def held_checkpoint():
            entered.set()
            stop = time.monotonic() + 5
            while time.monotonic() < stop:
                outcome["checkpoints"] += 1
                checkpoint()
                time.sleep(0.01)
            raise ValueError("disconnect was not observed by the builder checkpoint")

        try:
            return original(lake, checkpoint=held_checkpoint, **kwargs)
        except GraphBuildAborted as exc:
            outcome["abort_reason"] = exc.reason
            raise
        finally:
            finished.set()

    address = urlsplit(url)
    with patch.object(graph, "investigation_graph", observed_build):
        with socket.create_connection((address.hostname, address.port), timeout=5) as sock:
            request = (
                f"GET {ROUTE} HTTP/1.1\r\nHost: {address.netloc}\r\n"
                f"Authorization: Bearer {credential}\r\nConnection: close\r\n\r\n"
            )
            sock.sendall(request.encode("ascii"))
            if not entered.wait(5):
                raise ValueError("disconnect probe never reached a builder checkpoint")
            closed_at = time.perf_counter()
            sock.shutdown(socket.SHUT_RDWR)
        if not finished.wait(5):
            raise ValueError("disconnected build did not stop")
        wait_for_release(app)
    if outcome.get("abort_reason") != "disconnected":
        raise ValueError("socket closure did not cancel the graph build")
    disconnect_receipt = {
        "injection": "hold at real builder checkpoint until loopback socket closes",
        **outcome,
        "release_seconds": time.perf_counter() - closed_at,
    }
    response = httpx.get(url + ROUTE, headers=headers, timeout=client_timeout, trust_env=False)
    if response.status_code != 200 or not response.json().get("data", {}).get("nodes"):
        raise ValueError("graph did not recover after lifecycle probes")
    wait_for_release(app)
    return {
        "deadline": deadline_receipt,
        "disconnect": disconnect_receipt,
        "slots_released": True,
        "recovery_http_status": response.status_code,
    }
