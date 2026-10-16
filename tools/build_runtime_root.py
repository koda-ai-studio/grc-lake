#!/usr/bin/env python3
"""Assemble the CPython overlay for the distroless runtime during image build.

Copy whole Debian runtime packages, including license files and dpkg status
records. Package metadata is required so scanners can identify their versions.
The distroless base supplies glibc, OpenSSL, zlib, libgcc and libstdc++.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGES = (
    "libbz2-1.0",
    "libffi8",
    "libgdbm6t64",
    "libgdbm-compat4t64",
    "liblzma5",
    "libsqlite3-0",
    "libzstd1",
    "tini",
)


def main() -> None:
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree("/usr/local", root / "usr/local", symlinks=True)
    # Server/CLI workloads do not use interactive terminal editing, curses, or
    # the optional system libuuid backend. uuid's standard Python fallback stays.
    for library in (root / "usr/local/lib").glob("python*/lib-dynload"):
        for pattern in ("readline.*.so", "_curses*.so", "_uuid.*.so"):
            for path in library.glob(pattern):
                path.unlink()
    for library in (root / "usr/local/lib").glob("python*/ensurepip"):
        shutil.rmtree(library)
    status_dir = root / "var/lib/dpkg/status.d"
    status_dir.mkdir(parents=True)
    for package in PACKAGES:
        paths = subprocess.check_output(["dpkg-query", "-L", package], text=True).splitlines()
        for name in paths:
            source = Path(name)
            if not source.is_absolute():
                continue
            target = root / source.relative_to("/")
            if source.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(os.readlink(source))
            elif source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        status = subprocess.check_output(["dpkg-query", "-s", package], text=True)
        if "Status: install ok installed" not in status:
            raise RuntimeError(f"runtime package is not installed: {package}")
        (status_dir / package).write_text(status)
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


if __name__ == "__main__":
    main()
