"""Real local TLS negotiations; no external deployment or credentials needed."""

from __future__ import annotations

import socket
import ssl
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from tools.check_tls_policy import check_endpoint

from security_lakehouse.netguard import _PinnedHTTPSHandler


@pytest.fixture
def tls_certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, True, False, False, True, True, None, None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_path, key_path


@contextmanager
def _endpoint(material, ciphers, version=ssl.TLSVersion.TLSv1_2):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = version
    context.set_ciphers(ciphers)
    context.load_cert_chain(*material)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    stopped = threading.Event()

    def serve():
        while not stopped.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            with conn:
                conn.settimeout(2)
                try:
                    with context.wrap_socket(conn, server_side=True):
                        pass
                except ssl.SSLError:
                    pass  # Expected for intentionally incompatible probes.

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stopped.set()
        thread.join(timeout=3)
        listener.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_probe_accepts_forward_secret_endpoint(tls_certificate, version):
    with _endpoint(tls_certificate, "ECDHE-RSA-AES128-GCM-SHA256", version) as port:
        result = check_endpoint("localhost", port, cafile=str(tls_certificate[0]))
    assert result["passed"], result


def test_probe_rejects_endpoint_that_also_accepts_static_rsa(tls_certificate):
    with _endpoint(tls_certificate, "ECDHE-RSA-AES128-GCM-SHA256:AES128-GCM-SHA256") as port:
        result = check_endpoint("localhost", port, cafile=str(tls_certificate[0]))
    assert not result["passed"]
    assert "accepted TLS 1.2 static RSA" in result["error"]


def test_untrusted_certificate_is_not_reported_as_secure(tls_certificate):
    with _endpoint(tls_certificate, "ECDHE-RSA-AES128-GCM-SHA256") as port:
        result = check_endpoint("localhost", port)
    assert not result["passed"]
    assert "CERTIFICATE_VERIFY_FAILED" in result["error"]


def test_guarded_https_context_rejects_static_rsa(tls_certificate):
    context = _PinnedHTTPSHandler("test")._context
    context.load_verify_locations(cafile=str(tls_certificate[0]))
    with (
        _endpoint(tls_certificate, "AES128-GCM-SHA256") as port,
        socket.create_connection(("localhost", port), timeout=2) as connection,
        pytest.raises(ssl.SSLError),
    ):
        context.wrap_socket(connection, server_hostname="localhost")


def test_hostname_mismatch_does_not_qualify(tls_certificate):
    with _endpoint(tls_certificate, "ECDHE-RSA-AES128-GCM-SHA256") as port:
        result = check_endpoint("127.0.0.1", port, cafile=str(tls_certificate[0]))
    assert not result["passed"]
    assert "CERTIFICATE_VERIFY_FAILED" in result["error"]


def test_cli_returns_failure_for_inconclusive_probe(monkeypatch, capsys):
    from tools import check_tls_policy

    def timeout(*args):
        raise TimeoutError("test timeout")

    monkeypatch.setattr(check_tls_policy, "_handshake", timeout)
    assert check_tls_policy.main(["localhost"]) == 1
    assert '"passed": false' in capsys.readouterr().out
