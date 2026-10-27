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
