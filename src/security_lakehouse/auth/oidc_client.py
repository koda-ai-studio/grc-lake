"""OIDC verification policy applied to cached and refreshed IdP keys."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from authlib.integrations.starlette_client import StarletteOAuth2App

_SIGNING_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)


def _strong_signing_key(key: Any) -> bool:
    """Filter strength and purpose; Authlib still parses and verifies the key."""
    if not isinstance(key, dict) or key.get("use", "sig") != "sig":
        return False
    if "key_ops" in key and (not isinstance(key["key_ops"], list) or "verify" not in key["key_ops"]):
        return False
    if "alg" in key and (not isinstance(key["alg"], str) or key["alg"] not in _SIGNING_ALGORITHMS):
        return False
    if key.get("kty") == "RSA":
        modulus = key.get("n")
        if not isinstance(modulus, str):
            return False
        try:
            decoded = base64.b64decode(modulus + "=" * (-len(modulus) % 4), altchars=b"-_", validate=True)
        except (ValueError, binascii.Error):
            return False
        return int.from_bytes(decoded, "big").bit_length() >= 2048
    curve = key.get("crv")
    if key.get("kty") == "EC":
        return isinstance(curve, str) and curve in {"P-256", "P-384", "P-521"}
    if key.get("kty") == "OKP":
        return isinstance(curve, str) and curve in {"Ed25519", "Ed448"}
    return False


class StrongKeyOAuth2App(StarletteOAuth2App):
    """Keep Authlib's signature/claim checks and reject weak or unsigned tokens."""

    async def load_server_metadata(self):
        metadata = await super().load_server_metadata()
        advertised = metadata.get("id_token_signing_alg_values_supported", ["RS256"])
        if not isinstance(advertised, list):
            raise ValueError("OIDC signing algorithms must be a list")
        allowed = [alg for alg in advertised if isinstance(alg, str) and alg in _SIGNING_ALGORITHMS]
        if not allowed:
            raise ValueError("OIDC provider has no supported signing algorithm")
        return {**metadata, "id_token_signing_alg_values_supported": allowed}

    async def fetch_jwk_set(self, force=False):
        jwks = await super().fetch_jwk_set(force=force)
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            self.server_metadata.pop("jwks", None)
            raise ValueError("OIDC provider returned an invalid signing key set")
        keys = [key for key in jwks["keys"] if _strong_signing_key(key)]
        if not keys:
            # Do not retain an unusable set after the IdP repairs its keys.
            self.server_metadata.pop("jwks", None)
            raise ValueError("OIDC provider has no supported signing key (RSA requires at least 2048 bits)")
        return {**jwks, "keys": keys}

    def __init__(self, *args, expected_issuer: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_issuer = expected_issuer

    async def parse_id_token(self, token, nonce, claims_options=None, claims_cls=None, leeway=120):
        # A matching authorized party (azp) must not substitute for our audience.
        options = {
            **(claims_options or {}),
            "iss": {"essential": True, "value": self.expected_issuer},
            "aud": {"essential": True, "value": self.client_id},
        }
        return await super().parse_id_token(token, nonce, claims_options=options, claims_cls=claims_cls, leeway=leeway)
