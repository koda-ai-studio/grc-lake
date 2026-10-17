#!/usr/bin/env python3
"""Probe a deployment's verified TLS handshake and TLS 1.2 static-RSA rejection.

No credentials or HTTP requests are sent. This is a bounded endpoint check,
not a cipher-suite inventory or a claim about every replica behind a hostname.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import ssl
from datetime import UTC, datetime
from typing import Any


def _handshake(host: str, port: int, context: ssl.SSLContext, timeout: float) -> dict[str, Any]:
    with (
        socket.create_connection((host, port), timeout=timeout) as connection,
        context.wrap_socket(connection, server_hostname=host) as tls,
    ):
        cipher = tls.cipher()
        return {
            "version": tls.version(),
            "cipher": cipher[0] if cipher else None,
            "bits": cipher[2] if cipher else None,
            "certificate_sha256": hashlib.sha256(tls.getpeercert(binary_form=True) or b"").hexdigest(),
        }


def check_endpoint(host: str, port: int = 443, *, cafile: str | None = None, timeout: float = 5) -> dict[str, Any]:
    """Require a verified forward-secret connection and reject static RSA."""
    result: dict[str, Any] = {
        "host": host,
        "port": port,
        "checked_at": datetime.now(UTC).isoformat(),
        "passed": False,
        "scope": "One verified connection plus one TLS 1.2 static-RSA probe; not an exhaustive TLS audit",
    }
    try:
        context = ssl.create_default_context(cafile=cafile)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        strong = _handshake(host, port, context, timeout)
        result["negotiated"] = strong
        cipher = strong["cipher"] or ""
        if strong["version"] not in {"TLSv1.2", "TLSv1.3"} or not (
            strong["version"] == "TLSv1.3" or cipher.startswith(("ECDHE-", "DHE-"))
        ):
            result["error"] = "Verified connection did not negotiate forward secrecy"
            return result
        # A fresh context has no PSK/session ticket. Keep CA and hostname
        # verification enabled even when probing an undesirable key exchange.
        rsa_only = ssl.create_default_context(cafile=cafile)
        rsa_only.minimum_version = rsa_only.maximum_version = ssl.TLSVersion.TLSv1_2
        rsa_only.set_ciphers("AES128-GCM-SHA256:AES256-GCM-SHA384")
        try:
            result["static_rsa"] = _handshake(host, port, rsa_only, timeout)
            result["error"] = "Endpoint accepted TLS 1.2 static RSA key exchange"
        except ssl.SSLError as exc:
            # Certificate failures, EOF, timeouts and resets are inconclusive.
            if exc.reason not in {
                "SSLV3_ALERT_HANDSHAKE_FAILURE",
                "TLSV1_ALERT_PROTOCOL_VERSION",
                "SSLV3_ALERT_INSUFFICIENT_SECURITY",
            }:
                raise
            result["static_rsa"] = {"rejected": True, "reason": exc.reason}
            result["passed"] = True
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Hostname, without a URL scheme or path")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--cafile", help="PEM CA bundle for a private PKI; verification remains enabled")
    args = parser.parse_args(argv)
    result = check_endpoint(args.host, args.port, cafile=args.cafile)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
