"""Probe installed native dependencies and the shell-free image boundary."""

import bz2
import ctypes
import dbm.gnu
import gzip
import importlib.util
import lzma
import os
import pyexpat
import sqlite3
import ssl
import stat
import tempfile
import uuid
from pathlib import Path

assert os.getuid() == 1100, "runtime must retain the deployment UID"
for module in ("pip", "ensurepip", "readline", "_curses", "_uuid"):
    assert importlib.util.find_spec(module) is None, f"unexpected runtime module: {module}"
for name in (
    "/bin/sh",
    "/bin/bash",
    "/usr/bin/apt-get",
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
assert ssl.create_default_context().check_hostname
assert pyexpat.version_info >= (2, 8, 5), "bundled Expat security floor"
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
status = Path("/var/lib/dpkg/status.d")
for package in (
    "libbz2-1.0",
    "libffi8",
    "libgdbm6t64",
    "libgdbm-compat4t64",
    "liblzma5",
    "libsqlite3-0",
    "libzstd1",
    "tini",
):
    record = (status / package).read_text()
    assert f"Package: {package}\n" in record and "Status: install ok installed" in record
print("Runtime dependency and package-inventory checks passed.")
