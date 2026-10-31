"""Disk-backed navigation of one completed, scope-bound graph snapshot."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from security_lakehouse.investigation_index import ROOT_KINDS

__all__ = ["connect", "initialize", "populate", "query"]


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA cache_size=-8192")
    connection.execute("PRAGMA temp_store=FILE")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA cache_size=-8192;
        PRAGMA temp_store=FILE;
        PRAGMA trusted_schema=OFF;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL,
            folded TEXT NOT NULL, account TEXT NOT NULL, framework TEXT NOT NULL,
            data TEXT NOT NULL, ordinal INTEGER NOT NULL
        );
        CREATE TABLE edges (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL,
            data TEXT NOT NULL, ordinal INTEGER NOT NULL
        );
    """)


def populate(
    connection: sqlite3.Connection,
    nodes: Iterable[dict],
    edges: Iterable[dict],
    *,
    version: str,
    key: str,
    frameworks: Any,
    check: Callable[[], None],
) -> None:
    for ordinal, node in enumerate(nodes):
        check()
        connection.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?)",
            (
                node["id"],
                node["kind"],
                node["label"],
                (node["label"] + " " + node["id"]).casefold(),
                node.get("source_account_id", ""),
                node.get("framework_id", ""),
                json.dumps(node),
                ordinal,
            ),
        )
    for ordinal, edge in enumerate(edges):
        check()
        connection.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?)",
            (
                edge["id"],
                edge["source"],
                edge["target"],
                json.dumps(edge),
                ordinal,
            ),
        )
    connection.executescript("""
        CREATE INDEX edges_source ON edges(source, target);
        CREATE INDEX edges_target ON edges(target, source);
        CREATE INDEX nodes_kind ON nodes(kind, id);
        CREATE TABLE neighbors (source TEXT NOT NULL, target TEXT NOT NULL, PRIMARY KEY(source,target)) WITHOUT ROWID;
        INSERT OR IGNORE INTO neighbors SELECT source,target FROM edges;
        INSERT OR IGNORE INTO neighbors SELECT target,source FROM edges;
        CREATE TABLE roots (view TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL,label TEXT NOT NULL,
            folded TEXT NOT NULL,account TEXT NOT NULL,priority INTEGER NOT NULL,degree INTEGER NOT NULL,observed INTEGER NOT NULL);
        CREATE INDEX roots_order ON roots(view,priority,degree DESC,account,id);
        CREATE UNIQUE INDEX roots_identity ON roots(view,id);
        CREATE INDEX roots_id ON roots(id);
    """)
    # Keep each root lookup edges-first; a kind-first plan rescans all evidence per asset.
    defaults = {}
    for view, kinds in ROOT_KINDS.items():
        preferred = "environment" if view == "environment" else "control"
        placeholders = ",".join("?" for _ in kinds)
        connection.execute(
            """INSERT INTO roots SELECT ?,n.id,n.kind,n.label,n.folded,n.account,n.kind<>?,
            (SELECT count(*) FROM neighbors a WHERE a.source=n.id),
            EXISTS(SELECT 1 FROM edges e CROSS JOIN nodes t ON t.id=e.target WHERE e.source=n.id AND t.kind='evidence_type')
            FROM nodes n WHERE n.kind IN ("""
            + placeholders
            + ")",
            (view, preferred, *sorted(kinds)),
        )
        row = connection.execute(
            """SELECT id FROM roots WHERE view=? ORDER BY
            CASE WHEN kind='control' AND observed THEN CASE WHEN id='control:SOC2-CC6.1' THEN 0 ELSE 1 END ELSE 2 END,
            priority,degree DESC,account,id LIMIT 1""",
            (view,),
        ).fetchone()
        defaults[view] = row[0] if row else None
    connection.executemany(
        "INSERT INTO metadata VALUES (?,?)",
        (
            ("version", json.dumps(version)),
            ("key", json.dumps(key)),
            ("defaults", json.dumps(defaults)),
            ("frameworks", json.dumps({fid: {"name": row.get("name", fid)} for fid, row in frameworks.items()})),
            ("counts", json.dumps(dict(connection.execute("SELECT kind,count(*) FROM nodes GROUP BY kind")))),
        ),
    )
    check()
    connection.commit()


def query(
    connection: sqlite3.Connection,
    *,
    key: str,
    check: Callable[[], None],
    root: str | None,
    view: str,
    depth: int,
    limit: int,
    layers: set[str] | None,
    search: str,
    root_offset: int,
    framework: str,
    control_offset: int,
    expected_version: str | None,
) -> dict[str, Any]:
    """Keep cardinality, traversal sets and ordering in SQLite, including high-degree roots."""
    failure: list[BaseException] = []

    def progress() -> int:
        try:
            check()
        except (RuntimeError, ValueError, OSError, AssertionError, KeyboardInterrupt, SystemExit) as exc:
            # SQLite discards callback exceptions; rethrow after it interrupts the statement.
            failure.append(exc)
            return 1
        return 0

    connection.set_progress_handler(progress, 1000)
    try:
        return _query(
            connection,
            key=key,
            check=check,
            root=root,
            view=view,
            depth=depth,
            limit=limit,
            layers=layers,
            search=search,
            root_offset=root_offset,
            framework=framework,
            control_offset=control_offset,
            expected_version=expected_version,
        )
    except sqlite3.OperationalError:
        if failure:
            raise failure[0] from None
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _query(
    db: sqlite3.Connection,
    *,
    key: str,
    check: Callable[[], None],
    root: str | None,
    view: str,
    depth: int,
    limit: int,
    layers: set[str] | None,
    search: str,
    root_offset: int,
    framework: str,
    control_offset: int,
    expected_version: str | None,
) -> dict[str, Any]:
    check()
    meta = {name: json.loads(value) for name, value in db.execute("SELECT key,value FROM metadata")}
    if meta["key"] != key:
        raise ValueError("graph index scope changed")
    if expected_version and meta["version"] != expected_version:
        raise ValueError("graph version changed; refresh before expanding")
    if layers and set(meta["counts"]).issubset(layers):
        layers = None
    db.execute("CREATE TEMP TABLE layers (kind TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO layers VALUES (?)", ((kind,) for kind in layers or meta["counts"]))
    db.execute(
        "CREATE TEMP VIEW eligible AS SELECT id,kind,framework FROM nodes WHERE kind IN (SELECT kind FROM layers)"
    )
    preferred = "environment" if view == "environment" else "control"
    if not layers and not search:
        if root is None:
            root = meta["defaults"][view]
        root_count = sum(meta["counts"].get(kind, 0) for kind in ROOT_KINDS[view])
        roots = [
            dict(zip(("id", "label", "kind"), row, strict=True))
            for row in db.execute(
                "SELECT id,label,kind FROM roots WHERE view=? ORDER BY priority,degree DESC,account,id LIMIT 50 OFFSET ?",
                (view, root_offset),
            )
        ]
    else:
        # Filtered root ranking stays in disk-backed scratch space; neighborhoods never become Python inventories.
        db.execute(
            "CREATE TEMP TABLE choices (id TEXT PRIMARY KEY,kind TEXT,label TEXT,account TEXT,degree INTEGER,observed INTEGER)"
        )
        if layers:
            db.execute(
                """INSERT INTO choices
                SELECT n.id,n.kind,n.label,n.account,
                    (SELECT count(*) FROM neighbors a CROSS JOIN eligible e ON e.id=a.target WHERE a.source=n.id),
                    EXISTS(SELECT 1 FROM edges a CROSS JOIN eligible e ON e.id=a.target
                        WHERE a.source=n.id AND e.kind='evidence_type')
                FROM roots n WHERE n.view=? AND n.kind IN (SELECT kind FROM layers) AND instr(n.folded,?)>0""",
                (view, search.casefold()),
            )
        else:
            db.execute(
                """INSERT INTO choices SELECT id,kind,label,account,degree,observed FROM roots
                WHERE view=? AND instr(folded,?)>0""",
                (view, search.casefold()),
            )
        order = "kind<>?,degree DESC,account,id"
        if root is None:
            row = db.execute(
                "SELECT id FROM choices ORDER BY CASE WHEN kind='control' AND observed THEN "
                "CASE WHEN id='control:SOC2-CC6.1' THEN 0 ELSE 1 END ELSE 2 END," + order + " LIMIT 1",
                (preferred,),
            ).fetchone()
            root = row[0] if row else None
        root_count = db.execute("SELECT count(*) FROM choices").fetchone()[0]
        roots = [
            dict(zip(("id", "label", "kind"), row, strict=True))
            for row in db.execute(
                "SELECT id,label,kind FROM choices ORDER BY " + order + " LIMIT 50 OFFSET ?", (preferred, root_offset)
            )
        ]
    present = db.execute("SELECT 1 FROM eligible WHERE id=?", (root,)).fetchone() is not None
    db.executescript("""
        CREATE TEMP TABLE selected (id TEXT PRIMARY KEY,distance INTEGER NOT NULL,upstream INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TEMP TABLE frontier (id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TEMP TABLE following (id TEXT PRIMARY KEY) WITHOUT ROWID;
    """)
    if present:
        db.execute("INSERT INTO selected VALUES (?,0,0)", (root,))
    kind_row = db.execute("SELECT kind FROM nodes WHERE id=?", (root,)).fetchone()
    fast_count = None
    if depth == 1 and view != "controls" and not layers and (not kind_row or kind_row[0] != "safeguard"):
        if present:
            degree = db.execute("SELECT degree FROM roots WHERE id=? LIMIT 1", (root,)).fetchone()
            count = (
                degree[0]
                if degree
                else db.execute("SELECT count(*) FROM neighbors WHERE source=?", (root,)).fetchone()[0]
            )
            self_edge = (
                db.execute("SELECT 1 FROM neighbors WHERE source=? AND target=?", (root, root)).fetchone() is not None
            )
            fast_count = 1 + count - int(self_edge)
            db.execute(
                "INSERT INTO selected SELECT target,1,0 FROM neighbors WHERE source=? AND target<>? ORDER BY target LIMIT ?",
                (root, root, limit - 1),
            )
        else:
            fast_count = 0
    else:
        for direction in ("out", "in") if view == "controls" else ("both",):
            db.execute("DELETE FROM frontier")
            if present:
                db.execute("INSERT INTO frontier VALUES (?)", (root,))
            for hop in range(1, depth + 1):
                check()
                db.execute("DELETE FROM following")
                # Keep the frontier outermost: a kind-first plan scans unrelated evidence on every hop.
                if direction == "both":
                    db.execute(
                        """INSERT OR IGNORE INTO following SELECT a.target FROM frontier f
                        CROSS JOIN nodes n ON n.id=f.id CROSS JOIN neighbors a ON a.source=f.id
                        CROSS JOIN eligible e ON e.id=a.target
                        WHERE (f.id=? OR n.kind NOT IN ('framework','control','safeguard'))
                          AND NOT EXISTS(SELECT 1 FROM selected s WHERE s.id=a.target)""",
                        (root,),
                    )
                elif direction == "out":
                    db.execute("""INSERT OR IGNORE INTO following SELECT a.target FROM frontier f
                        CROSS JOIN edges a ON a.source=f.id CROSS JOIN eligible e ON e.id=a.target
                        WHERE NOT EXISTS(SELECT 1 FROM selected s WHERE s.id=a.target)""")
                else:
                    # Incoming traversal is independent of nodes already reached downstream.
                    db.execute(
                        """INSERT OR IGNORE INTO following SELECT a.source FROM frontier f
                        CROSS JOIN edges a ON a.target=f.id CROSS JOIN eligible e ON e.id=a.source
                        WHERE a.source<>? AND NOT EXISTS(
                            SELECT 1 FROM selected s WHERE s.id=a.source AND s.upstream=1)""",
                        (root,),
                    )
                db.execute(
                    """INSERT INTO selected SELECT id,?,? FROM following WHERE true
                    ON CONFLICT(id) DO UPDATE SET distance=min(distance,excluded.distance),
                    upstream=max(upstream,excluded.upstream)""",
                    (hop, int(direction == "in")),
                )
                db.execute("ALTER TABLE frontier RENAME TO previous")
                db.execute("ALTER TABLE following RENAME TO frontier")
                db.execute("ALTER TABLE previous RENAME TO following")
                if direction == "out":
                    db.execute("DELETE FROM following")
                    db.execute("""INSERT OR IGNORE INTO following SELECT a.source FROM frontier f
                        CROSS JOIN nodes n ON n.id=f.id CROSS JOIN edges a ON a.target=f.id
                        CROSS JOIN eligible e ON e.id=a.source
                        WHERE n.kind='evidence_type' AND e.kind='source'
                          AND NOT EXISTS(SELECT 1 FROM selected s WHERE s.id=a.source)""")
                    db.execute("INSERT INTO selected SELECT id,?,0 FROM following", (hop + 1,))
    framework_groups = []
    selected_framework = ""
    control_count = 0
    node = db.execute("SELECT kind FROM nodes WHERE id=?", (root,)).fetchone()
    if node and node[0] == "safeguard":
        db.execute(
            "CREATE TEMP TABLE controls AS SELECT DISTINCT n.id,n.framework FROM edges a "
            "JOIN eligible n ON n.id=a.source WHERE a.target=? AND n.kind='control' AND ?",
            (root, int(present)),
        )
        framework_groups = [
            {"framework_id": fid, "label": meta["frameworks"].get(fid, {}).get("name", fid), "control_count": count}
            for fid, count in db.execute(
                "SELECT framework,count(*) FROM controls GROUP BY framework ORDER BY framework"
            )
        ]
        selected_framework = framework or (framework_groups[0]["framework_id"] if framework_groups else "")
        control_count = db.execute("SELECT count(*) FROM controls WHERE framework=?", (selected_framework,)).fetchone()[
            0
        ]
        db.execute("CREATE TEMP TABLE page (id TEXT PRIMARY KEY)")
        db.execute(
            "INSERT OR IGNORE INTO page SELECT id FROM controls WHERE framework=? ORDER BY id LIMIT 5 OFFSET ?",
            (selected_framework, control_offset),
        )
        db.execute("INSERT OR IGNORE INTO page VALUES (?)", ("framework:" + selected_framework,))
        db.execute("""DELETE FROM selected WHERE id IN
            (SELECT id FROM nodes WHERE kind IN ('control','framework','ccf_family','ccf_category'))
            AND id NOT IN (SELECT id FROM page)""")
    matching = fast_count if fast_count is not None else db.execute("SELECT count(*) FROM selected").fetchone()[0]
    db.execute(
        "CREATE TEMP TABLE kept AS SELECT id,distance,upstream FROM selected ORDER BY distance,upstream DESC,id LIMIT ?",
        (limit,),
    )
    db.execute("CREATE UNIQUE INDEX kept_id ON kept(id)")
    nodes = [
        json.loads(row[0])
        for row in db.execute(
            "SELECT n.data FROM kept k JOIN nodes n ON n.id=k.id ORDER BY k.distance,k.upstream DESC,k.id"
        )
    ]
    edges = [
        json.loads(row[0])
        for row in db.execute(
            "SELECT a.data FROM kept k CROSS JOIN kept t CROSS JOIN edges a ON a.source=k.id AND a.target=t.id ORDER BY a.ordinal"
        )
    ]
    check()
    return {
        "nodes": nodes,
        "edges": edges,
        "counts": meta["counts"],
        "version": meta["version"],
        "root": root,
        "root_missing": root is not None and not present,
        "roots": roots,
        "root_count": root_count,
        "root_offset": root_offset,
        "next_root_offset": root_offset + 50 if root_offset + 50 < root_count else None,
        "framework_groups": framework_groups,
        "selected_framework": selected_framework,
        "control_count": control_count,
        "control_offset": control_offset,
        "next_control_offset": control_offset + 5 if control_offset + 5 < control_count else None,
        "depth": depth,
        "limit": limit,
        "truncated": matching > limit,
        "matching_nodes": matching,
        "boundary": "Recorded relationships; not network reachability or complete inventory",
    }
