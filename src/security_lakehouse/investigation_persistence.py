"""Atomic, process-independent reuse of a complete graph index for one lake scope."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from security_lakehouse import catalog
from security_lakehouse import investigation_sqlite as sql
from security_lakehouse import safeguards as safeguard_catalog
from security_lakehouse.generations import generation_identity, pinned_path, verify_generation
from security_lakehouse.investigation_staging import Staging
from security_lakehouse.io import canonical_sha256, file_sha256, file_version, read_json, write_json

MAX_INDEX_BYTES = 16 * 2**30
MIN_FREE_BYTES = 2 * 2**30

__all__ = ["read"]


@lru_cache(maxsize=1)
def _runtime_digest() -> str:
    package = Path(__file__).parent
    digest = hashlib.sha256()
    for source in sorted(package.rglob("*.py")):
        digest.update(str(source.relative_to(package)).encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def _path(lake: Path) -> Path:
    root = lake.resolve()
    directory = root / ".graph-index"
    for path in (directory, directory / "index.sqlite", directory / "index.json", directory / "build.lock"):
        if path.is_symlink():
            raise ValueError("graph index paths must not be symlinks")
    return directory / "index.sqlite"


def _matches(path, state):
    key, racy = state
    receipt_path = path.with_suffix(".json")
    if not path.exists() or not receipt_path.exists():
        return False
    receipt = read_json(receipt_path, base_dir=path.parent)
    _, version = file_version(path, base_dir=path.parent)
    if not isinstance(receipt, dict) or receipt.get("key") != key:
        return False
    if (
        (version.hex() != receipt.get("sha256"))
        if isinstance(version, bytes)
        else (list(version or ()) != receipt.get("stat"))
    ):
        return False
    try:
        with closing(sql.connect(path)) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='key'").fetchone()
            if row is None or json.loads(row[0]) != key:
                return False
            stored = db.execute("SELECT value FROM metadata WHERE key='source_digests'").fetchone()
            digests = json.loads(stored[0]) if stored else {}
            return all(digests.get(name) == digest for name, digest in racy.items())
    except (sqlite3.DatabaseError, ValueError) as exc:
        raise ValueError("graph index is unreadable; remove the derived index and rebuild") from exc


def read(lake, vendors, tenant, check, *, model_files, build_model, graph_version, allow_build=True, **query):
    def identity():
        versions, racy = [], {}
        for relative in (
            *model_files,
            "mart/security_lakehouse.sqlite",
            *(("entities/bindings.jsonl",) if tenant is not None else ()),
        ):
            path_name, version = file_version(lake / relative, base_dir=lake)
            versions.append((path_name, version))
        for source in (catalog.DEFAULT_FRAMEWORK_REGISTRY, safeguard_catalog.DEFAULT_FAMILIES):
            versions.append(file_version(source))
        stable = []
        for name, version in versions:
            check()
            if isinstance(version, bytes):
                racy[name] = version.hex()
                info = Path(name).stat()
                version = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            stable.append((name, version))
        return canonical_sha256(
            [_runtime_digest(), str(lake.resolve()), generation_identity(lake), tenant, vendors, stable]
        ), racy

    def unchanged(before):
        after = identity()
        return before[0] == after[0] and all(
            after[1].get(name, None) == digest if name in after[1] else file_sha256(name) == digest
            for name, digest in before[1].items()
        )

    vendors = vendors or []
    state = identity()
    key = state[0]
    path = _path(lake)
    if not _matches(path, state):
        if not allow_build:
            return None
        path.parent.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(path.parent / "build.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            while True:
                check()
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.025)
            if not _matches(path, state):
                for leftover in path.parent.glob(".building-*.sqlite*"):
                    if leftover.name.endswith((".sqlite", ".sqlite-journal")):
                        leftover.unlink()
                if shutil.disk_usage(path.parent).free < MIN_FREE_BYTES:
                    raise ValueError("insufficient free disk for graph index")
                descriptor, name = tempfile.mkstemp(prefix=".building-", suffix=".sqlite", dir=path.parent)
                os.close(descriptor)
                temporary = Path(name)
                sampled = 0.0
                failure = []

                def bounded():
                    nonlocal sampled
                    check()
                    now = time.monotonic()
                    if now - sampled >= 1:
                        sampled = now
                        if shutil.disk_usage(path.parent).free < MIN_FREE_BYTES:
                            raise ValueError("graph index disk floor reached")

                def progress():
                    try:
                        bounded()
                    except (RuntimeError, ValueError, OSError, AssertionError, KeyboardInterrupt, SystemExit) as exc:
                        # SQLite discards callback exceptions; rethrow after it interrupts the statement.
                        failure.append(exc)
                        return 1
                    return 0

                try:
                    generation = pinned_path(lake / "catalog/control_map.json").parent.parent
                    verify_generation(generation)
                    with closing(sqlite3.connect(temporary)) as db:
                        db.execute("PRAGMA page_size=4096")
                        db.execute(f"PRAGMA max_page_count={MAX_INDEX_BYTES // 4096}")
                        sql.initialize(db)
                        db.execute("PRAGMA temp.cache_size=-65536")
                        db.execute("PRAGMA temp.page_size=4096")
                        db.execute(f"PRAGMA temp.max_page_count={MAX_INDEX_BYTES // 4096}")
                        db.set_progress_handler(progress, 1000)
                        stage = Staging(db, lake, bounded)
                        nodes, edges, frameworks = build_model(lake, vendors, bounded, tenant, storage=stage)
                        version = graph_version(nodes.values(), edges.values(), bounded)
                        sql.populate(
                            db,
                            nodes.values(),
                            edges.values(),
                            version=version,
                            key=key,
                            frameworks=frameworks,
                            check=bounded,
                        )
                        db.execute("INSERT INTO metadata VALUES ('source_digests',?)", (json.dumps(state[1]),))
                        stage.drop()
                        db.commit()
                        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                            raise ValueError("graph index integrity check failed")
                    bounded()
                    if not unchanged(state):
                        raise ValueError("graph version changed while indexing; retry")
                    with temporary.open("rb") as stream:
                        os.fsync(stream.fileno())
                    digest = file_sha256(temporary)
                    os.replace(temporary, path)
                    info = path.stat()
                    write_json(
                        path.with_suffix(".json"),
                        {
                            "key": key,
                            "sha256": digest,
                            "stat": [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns],
                        },
                        base_dir=path.parent,
                    )
                except sqlite3.OperationalError:
                    if failure:
                        raise failure[0] from None
                    raise
                finally:
                    temporary.unlink(missing_ok=True)
                    temporary.with_name(temporary.name + "-journal").unlink(missing_ok=True)
        finally:
            os.close(fd)
    check()
    with closing(sql.connect(path)) as db:
        result = sql.query(db, key=key, check=check, **query)
    if not unchanged(state) or not _matches(path, state):
        raise ValueError("graph version changed while reading; retry")
    return result
