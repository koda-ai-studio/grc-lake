#!/usr/bin/env python3
"""Prepare the pinned vendor runtime and deployment identity.

The APK stage installs complete signed packages, licenses and inventory. This
step retains those records, removes optional interactive Python modules, and
sets the deployment identity.
"""

import os
import shutil
import sys
from pathlib import Path

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


def assemble_runtime(root: Path) -> None:
    inventory = root / "lib/apk/db/installed"
    if not inventory.is_file():
        raise RuntimeError("runtime package inventory is missing")
    installed = {line[2:] for line in inventory.read_text().splitlines() if line.startswith("P:")}
    missing = set(PACKAGES) - installed
    if missing:
        raise RuntimeError(f"missing runtime packages: {sorted(missing)}")
    # Server/CLI workloads do not use interactive terminal editing, curses, or
    # the optional system libuuid backend. uuid's standard Python fallback stays.
    for library in (root / "usr/lib").glob("python*/lib-dynload"):
        for pattern in ("readline.*.so", "_curses*.so", "_uuid.*.so"):
            for path in library.glob(pattern):
                path.unlink()
    for library in (root / "usr/lib").glob("python*/ensurepip"):
        shutil.rmtree(library)
    aliases = root / "usr/local/bin"
    aliases.mkdir(parents=True, exist_ok=True)
    for name in ("python", "python3"):
        (aliases / name).symlink_to("/usr/bin/python3.14")
    etc = root / "etc"
    etc.mkdir(exist_ok=True)
    (etc / "passwd").write_text(
        "root:x:0:0:root:/root:/sbin/nologin\ngrc-lake:x:1100:1100:GRC Lake:/home/grc-lake:/sbin/nologin\n"
    )
    (etc / "group").write_text("root:x:0:\ngrc-lake:x:1100:\n")
    for directory in ("home/grc-lake", "lake"):
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, 1100, 1100)


def validate_package_lock(root: Path, lock: Path) -> None:
    expected = set(lock.read_text().splitlines())
    installed = set()
    for record in (root / "lib/apk/db/installed").read_text().split("\n\n"):
        fields = dict(line.split(":", 1) for line in record.splitlines() if line.startswith(("P:", "V:")))
        if fields:
            installed.add(f"{fields['P']}={fields['V']}")
    if installed != expected:
        raise RuntimeError(
            f"runtime package lock mismatch: missing={sorted(expected - installed)}, "
            f"unexpected={sorted(installed - expected)}"
        )


def main() -> None:
    root = Path(sys.argv[1])
    validate_package_lock(root, Path(__file__).with_name("runtime-packages.txt"))
    assemble_runtime(root)


if __name__ == "__main__":
    main()
