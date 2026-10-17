"""Verify ID tokens through the configured OAuth client, without a live IdP."""

from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
import pytest

pytest.importorskip("authlib")
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from security_lakehouse.auth.oidc import OIDCConfig, build_oauth


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _material(bits, kid="test"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    numbers = key.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": kid, "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8)), "e": "AQAB"}
    return key, jwk


def _token(key, kid="test", **overrides):
    claims = {
        "sub": "human",
        "iss": "https://idp.test",
        "aud": "client",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "nonce": "nonce",
    } | overrides
    message = (
        _b64(json.dumps({"alg": "RS256", "kid": kid}).encode()) + "." + _b64(json.dumps(claims).encode())
    ).encode()
    return {"id_token": message.decode() + "." + _b64(key.sign(message, padding.PKCS1v15(), hashes.SHA256()))}


def _client(keys):
    client = build_oauth(OIDCConfig("https://idp.test", "client", "test-secret")).oidc
    client.server_metadata.update(
        {
            "_loaded_at": time.time(),
            "issuer": "https://idp.test",
            "jwks": {"keys": keys},
            "id_token_signing_alg_values_supported": ["RS256"],
        }
    )
    return client


def test_oidc_rejects_signed_token_with_1024_bit_key():
    key, jwk = _material(1024)
    with pytest.raises(ValueError, match="signing key"):
        asyncio.run(_client([jwk]).parse_id_token(_token(key), nonce="nonce"))


def test_oidc_accepts_2048_bit_key_alongside_weak_retired_key():
    key, jwk = _material(2048)
    _, retired = _material(1024, "retired")
    claims = asyncio.run(_client([retired, jwk]).parse_id_token(_token(key), nonce="nonce"))
    assert claims["sub"] == "human"


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://wrong.test"},
        {"aud": "wrong"},
        {"aud": "wrong", "azp": "client"},
        {"nonce": "wrong"},
        {"exp": 1},
    ],
)
def test_oidc_strong_key_does_not_bypass_claim_validation(claims):
    key, jwk = _material(2048)
    with pytest.raises(Exception, match="invalid_claim|missing_claim|expired_token"):
        asyncio.run(_client([jwk]).parse_id_token(_token(key, **claims), nonce="nonce"))


@pytest.mark.parametrize("bits", [1024, 2048])
def test_oidc_checks_rotated_keys_after_forced_refresh(bits):
    _, old = _material(2048, "old")
    key, new = _material(bits, "new")
    client = _client([old])
    client.server_metadata["jwks_uri"] = "https://idp.test/keys"
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={"keys": [new]})

    client.client_kwargs["transport"] = httpx.MockTransport(respond)
    if bits == 1024:
        with pytest.raises(ValueError, match="signing key"):
            asyncio.run(client.parse_id_token(_token(key, "new"), nonce="nonce"))
    else:
        assert asyncio.run(client.parse_id_token(_token(key, "new"), nonce="nonce"))["sub"] == "human"
    assert requests == ["https://idp.test/keys"]


@pytest.mark.parametrize("algorithms", [["none"], ["HS256"], [], "RS256"])
def test_oidc_rejects_unsafe_metadata_algorithms(algorithms):
    key, jwk = _material(2048)
    client = _client([jwk])
    client.server_metadata["id_token_signing_alg_values_supported"] = algorithms
    with pytest.raises(ValueError, match="signing algorithm"):
        asyncio.run(client.parse_id_token(_token(key), nonce="nonce"))


@pytest.mark.parametrize(
    "change", [{"n": "bad!"}, {"n": None}, {"use": "enc"}, {"key_ops": ["encrypt"]}, {"kty": "oct"}]
)
def test_oidc_rejects_unusable_signing_keys(change):
    key, jwk = _material(2048)
    with pytest.raises(ValueError, match="signing key"):
        asyncio.run(_client([jwk | change]).parse_id_token(_token(key), nonce="nonce"))


def test_oidc_recovers_after_provider_replaces_an_all_weak_key_set():
    _, weak = _material(1024)
    key, strong = _material(2048)
    client = _client([weak])
    client.server_metadata["jwks_uri"] = "https://idp.test/keys"
    client.client_kwargs["transport"] = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"keys": [strong]})
    )
    with pytest.raises(ValueError, match="signing key"):
        asyncio.run(client.parse_id_token(_token(key), nonce="nonce"))
    assert asyncio.run(client.parse_id_token(_token(key), nonce="nonce"))["sub"] == "human"


def test_oidc_discovery_cannot_replace_configured_issuer():
    key, jwk = _material(2048)
    client = _client([jwk])
    client.server_metadata["issuer"] = "https://wrong.test"
    with pytest.raises(Exception, match="invalid_claim"):
        asyncio.run(client.parse_id_token(_token(key, iss="https://wrong.test"), nonce="nonce"))


def test_oidc_rejects_tampered_signature():
    key, jwk = _material(2048)
    other, _ = _material(2048)
    with pytest.raises(Exception, match="bad_signature"):
        asyncio.run(_client([jwk]).parse_id_token(_token(other), nonce="nonce"))
