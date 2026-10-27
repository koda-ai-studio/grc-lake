"""Provider responses are capped on actual bytes, including short reads."""

import io

import pytest

from security_lakehouse.http_response import ResponseLimitError, read_bytes, read_json_response


class ShortReads(io.BytesIO):
    headers = {"Content-Length": "1"}

    def read(self, size=-1):
        assert 0 < size <= 64 * 1024
        return super().read(min(size, 3))


def test_short_reads_and_utf8_are_preserved_at_exact_limit():
    body = '{"text":"é"}'.encode()
    assert read_json_response(ShortReads(body), limit=len(body)) == {"text": "é"}


def test_limit_counts_bytes_without_trusting_content_length():
    response = ShortReads(b"a" * 100)
    with pytest.raises(ResponseLimitError) as caught:
        read_bytes(response, limit=10)
    assert response.tell() == 11
    assert caught.value.attributes()["collection_gap"] is True
    assert caught.value.attributes()["reason"] == "response_byte_limit"


def test_empty_response_and_invalid_json_are_not_replaced_with_success():
    assert read_bytes(io.BytesIO(b""), limit=1) == b""
    with pytest.raises(ValueError):
        read_json_response(io.BytesIO(b""))


def test_aggregate_budget_counts_responses_and_resets():
    from security_lakehouse import http_response

    with http_response.response_budget(max_bytes=6):
        assert read_bytes(io.BytesIO(b"abc")) == b"abc"
        with pytest.raises(ResponseLimitError) as caught:
            read_bytes(io.BytesIO(b"defg"))
        assert caught.value.attributes()["reason"] == "run_response_byte_limit"
        untouched = io.BytesIO(b"x")
        with pytest.raises(ResponseLimitError):
            read_bytes(untouched)
        assert untouched.tell() == 0
    assert read_bytes(io.BytesIO(b"unrelated")) == b"unrelated"


def test_nested_budget_restores_outer_budget():
    from security_lakehouse import http_response

    with http_response.response_budget(max_bytes=3):
        read_bytes(io.BytesIO(b"ab"))
        with http_response.response_budget(max_bytes=20):
            read_bytes(io.BytesIO(b"independent"))
        with pytest.raises(ResponseLimitError):
            read_bytes(io.BytesIO(b"cd"))


def test_concurrent_runs_do_not_share_budgets():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from security_lakehouse import http_response

    barrier = Barrier(2)

    def collect():
        with http_response.response_budget(max_bytes=6):
            first = read_bytes(io.BytesIO(b"abc"))
            barrier.wait(timeout=5)
            return first + read_bytes(io.BytesIO(b"def"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(collect) for _ in range(2)]
        assert [future.result() for future in futures] == [b"abcdef", b"abcdef"]
