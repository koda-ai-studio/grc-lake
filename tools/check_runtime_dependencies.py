"""Probe installed native dependencies and the shell-free image boundary."""

import bz2
import ctypes
import dbm.gnu
import gzip
import importlib.util
import lzma
import os
import pwd
import pyexpat
import sqlite3
import ssl
import stat
import tempfile
import uuid
from pathlib import Path

assert os.getuid() == os.getgid() == 1100, "runtime must retain the deployment UID/GID"
user = pwd.getpwuid(os.getuid())
assert user.pw_name == "grc-lake" and user.pw_dir == "/home/grc-lake"
assert Path.cwd() == Path(user.pw_dir) and os.access(user.pw_dir, os.W_OK)
for module in ("pip", "ensurepip", "readline", "_curses", "_uuid"):
    assert importlib.util.find_spec(module) is None, f"unexpected runtime module: {module}"
for name in (
    "/bin/sh",
    "/bin/bash",
    "/usr/bin/apt-get",
    "/sbin/apk",
    "/usr/bin/apk",
    "/usr/bin/dpkg",
    "/usr/bin/mount",
    "/usr/bin/nsenter",
    "/usr/bin/perl",
):
    assert not Path(name).exists(), f"unexpected runtime program: {name}"
payload = b"grc-lake compression smoke" * 100
for codec in (bz2, gzip, lzma):
    assert codec.decompress(codec.compress(payload)) == payload
assert sqlite3.connect(":memory:").execute("select 1").fetchone() == (1,)
context = ssl.create_default_context()
assert context.check_hostname
assert context.cert_store_stats()["x509_ca"] > 0, "system TLS trust store is empty"
assert pyexpat.version_info >= (2, 8, 5), "Expat security floor"
assert uuid.uuid4().version == 4
assert ctypes.CDLL(None)
with tempfile.TemporaryDirectory() as folder, dbm.gnu.open(str(Path(folder) / "probe"), "c") as database:
    database[b"key"] = b"value"
    assert database[b"key"] == b"value"
for root, _directories, files in os.walk("/usr"):
    for name in files:
        path = Path(root) / name
        if path.is_symlink():
            continue
        assert not path.stat().st_mode & (stat.S_ISUID | stat.S_ISGID), f"elevated runtime file: {path}"
inventory = Path("/lib/apk/db/installed").read_text()
packages = {line[2:] for line in inventory.splitlines() if line.startswith("P:")}
for package in (
    "libbz2-1",
    "libffi",
    "gdbm",
    "xz",
    "sqlite-libs",
    "libzstd1",
    "tini",
    "libstdc++",
    "zlib",
    "python-3.14-base",
    "openssl-4.0-libssl",
    "openssl-4.0-libcrypto",
    "ca-certificates-bundle",
):
    assert package in packages, f"missing runtime package record: {package}"
for package in ("busybox", "bash", "apk-tools"):
    assert package not in packages, f"unexpected runtime package: {package}"
print("Runtime dependency and package-inventory checks passed.")
