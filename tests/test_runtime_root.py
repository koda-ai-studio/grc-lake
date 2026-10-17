"""The runtime overlay retains vendor inventory and excludes build tools."""

import pytest
from tools import build_runtime_root

PACKAGES = (
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
)


def test_overlay_preserves_vendor_inventory_and_python(tmp_path, monkeypatch):
    root = tmp_path / "root"
    inventory = root / "lib/apk/db/installed"
    inventory.parent.mkdir(parents=True)
    content = "\n\n".join(f"P:{name}\nV:1.0-r0" for name in PACKAGES) + "\n"
    inventory.write_text(content)
    native = root / "usr/lib/libsqlite3.so.0"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"vendor-library")
    (root / "usr/local").mkdir()
    source = root / "usr"
    extensions = source / "lib/python3.14/lib-dynload"
    extensions.mkdir(parents=True)
    for name in (
        "_ssl.cpython-314-aarch64-linux-gnu.so",
        "readline.cpython-314-aarch64-linux-gnu.so",
        "_uuid.cpython-314-aarch64-linux-gnu.so",
        "_curses.cpython-314-aarch64-linux-gnu.so",
    ):
        (extensions / name).write_bytes(b"python-extension")
    (source / "lib/python3.14/ensurepip").mkdir()
    ownership = {}
    monkeypatch.setattr(build_runtime_root.os, "chown", lambda p, u, g: ownership.update({p: (u, g)}))
    build_runtime_root.assemble_runtime(root)
    assert (root / "usr/local/bin/python").readlink().as_posix() == "/usr/bin/python3.14"
    assert inventory.read_text() == content
    assert native.read_bytes() == b"vendor-library"
    copied = root / "usr/lib/python3.14"
    assert (copied / "lib-dynload/_ssl.cpython-314-aarch64-linux-gnu.so").read_bytes() == b"python-extension"
    for name in (
        "readline.cpython-314-aarch64-linux-gnu.so",
        "_uuid.cpython-314-aarch64-linux-gnu.so",
        "_curses.cpython-314-aarch64-linux-gnu.so",
    ):
        assert not (copied / "lib-dynload" / name).exists()
    assert not (copied / "ensurepip").exists()
    assert ownership[root / "home/grc-lake"] == (1100, 1100)
    assert ownership[root / "lake"] == (1100, 1100)
    assert "grc-lake:x:1100:1100:" in (root / "etc/passwd").read_text()


def test_overlay_rejects_missing_vendor_inventory(tmp_path):
    with pytest.raises(RuntimeError, match="package inventory"):
        build_runtime_root.assemble_runtime(tmp_path)


def test_overlay_rejects_incomplete_vendor_inventory(tmp_path):
    inventory = tmp_path / "lib/apk/db/installed"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("P:libbz2-1\nV:1.0-r0\n")
    with pytest.raises(RuntimeError, match="missing runtime packages"):
        build_runtime_root.assemble_runtime(tmp_path)


@pytest.mark.parametrize("records", ["P:zlib\nV:0.9-r0\n", "P:zlib\nV:1.0-r0\n\nP:extra\nV:1.0-r0\n"])
def test_vendor_resolution_cannot_drift_from_lock(tmp_path, records):
    inventory = tmp_path / "lib/apk/db/installed"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(records)
    lock = tmp_path / "runtime-packages.txt"
    lock.write_text("zlib=1.0-r0\n")
    with pytest.raises(RuntimeError, match="package lock"):
        build_runtime_root.validate_package_lock(tmp_path, lock)


def test_vendor_resolution_matches_lock(tmp_path):
    inventory = tmp_path / "lib/apk/db/installed"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("P:zlib\nV:1.0-r0\n")
    lock = tmp_path / "runtime-packages.txt"
    lock.write_text("zlib=1.0-r0\n")
    build_runtime_root.validate_package_lock(tmp_path, lock)
