"""The Python CA bundle shipped with GRC Lake must not trust distrusted roots."""

from __future__ import annotations

import certifi

# certifi 2026.10.23 removed these roots after their distrust; outbound HTTPS from
# connectors uses certifi's bundle by default, so an older pin would still trust them.
DISTRUSTED_ROOTS = ("emSign ECC Root CA - C3", "emSign Root CA - C1")


def test_certifi_bundle_excludes_distrusted_roots() -> None:
    bundle = open(certifi.where(), encoding="utf-8").read()
    assert not [label for label in DISTRUSTED_ROOTS if f'# Label: "{label}"' in bundle]
