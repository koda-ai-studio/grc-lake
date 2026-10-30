"""The installed JOSE parser rejects oversized input before copying segments."""

import pytest

pytest.importorskip("joserfc")
from joserfc import jws
from joserfc.errors import ExceededSizeError


def test_oversized_jws_is_rejected_before_splitting_segments():
    class UnsplitToken(bytes):
        def split(self, *args, **kwargs):
            pytest.fail("oversized compact token was split before enforcing its size limit")

    registry = jws.JWSRegistry()
    registry.max_header_length = 8
    registry.max_payload_length = 8
    registry.max_signature_length = 8
    token = UnsplitToken(b"header." + b"x" * 32 + b".signature")
    with pytest.raises(ExceededSizeError):
        jws.deserialize_compact(token, None, registry=registry)
