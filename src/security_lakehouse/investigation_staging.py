"""SQLite scratch maps keep graph construction independent of Python inventory size."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, MutableMapping
from typing import Any

from security_lakehouse.asset_names import asset_name_key
from security_lakehouse.ccf_queries import read_summary
from security_lakehouse.domain_identity import source_asset_key
from security_lakehouse.io import canonical_sha256, iter_jsonl
from security_lakehouse.models import instant_sort_key

__all__ = ["Staging"]


def encoded(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


class Rows(MutableMapping):
    def __init__(self, db: sqlite3.Connection, space: str):
        self.db, self.space = db, space

    def __getitem__(self, key):
        row = self.db.execute("SELECT data FROM objects WHERE space=? AND key=?", (self.space, encoded(key))).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __setitem__(self, key, value):
        self.db.execute(
            "INSERT INTO objects(space,key,data) VALUES (?,?,?) "
            "ON CONFLICT(space,key) DO UPDATE SET data=excluded.data",
            (self.space, encoded(key), encoded(value)),
        )

    def __delitem__(self, key):
        if not self.db.execute("DELETE FROM objects WHERE space=? AND key=?", (self.space, encoded(key))).rowcount:
            raise KeyError(key)

    def __iter__(self) -> Iterator:
        for row in self.db.execute("SELECT key FROM objects WHERE space=? ORDER BY ordinal", (self.space,)):
            value = json.loads(row[0])
            yield tuple(value) if isinstance(value, list) else value

    def __len__(self):
        return self.db.execute("SELECT count(*) FROM objects WHERE space=?", (self.space,)).fetchone()[0]

    def __contains__(self, key):
        return (
            self.db.execute("SELECT 1 FROM objects WHERE space=? AND key=?", (self.space, encoded(key))).fetchone()
            is not None
        )

    def values(self):
        for row in self.db.execute("SELECT data FROM objects WHERE space=? ORDER BY ordinal", (self.space,)):
            yield json.loads(row[0])

    def setdefault(self, key, default=None):
        self.db.execute(
            "INSERT OR IGNORE INTO objects(space,key,data) VALUES (?,?,?)", (self.space, encoded(key), encoded(default))
        )
        return self[key]


class Staging:
    def __init__(self, db: sqlite3.Connection, lake, check):
        self.db, self.check = db, check
        db.executescript("""
            CREATE TEMP TABLE objects (ordinal INTEGER PRIMARY KEY,space TEXT NOT NULL,key TEXT NOT NULL,data TEXT NOT NULL,UNIQUE(space,key));
            CREATE INDEX objects_order ON objects(space,ordinal);
            CREATE TEMP TABLE events (ordinal INTEGER PRIMARY KEY,hash TEXT NOT NULL,data TEXT NOT NULL);
            CREATE INDEX events_order ON events(hash,ordinal);
            CREATE TEMP TABLE asset_types (account TEXT,asset TEXT,type TEXT,PRIMARY KEY(account,asset,type)) WITHOUT ROWID;
            CREATE TEMP TABLE evidence (account TEXT,event TEXT,asset TEXT,id TEXT,PRIMARY KEY(account,event,asset,id)) WITHOUT ROWID;
            CREATE TEMP TABLE findings (control TEXT,id TEXT,severity INTEGER,PRIMARY KEY(control,id)) WITHOUT ROWID;
            CREATE INDEX finding_order ON findings(control,severity,id);
        """)
        self.nodes, self.edges = Rows(db, "nodes"), Rows(db, "edges")
        self.triage = Rows(db, "triage")
        self.assessment = read_summary(lake)
        for row in iter_jsonl(lake / "gold/violation_tracking.jsonl", missing_ok=True, base_dir=lake):
            check()
            previous = self.triage.get(row["violation_id"])
            if previous is None or instant_sort_key(row.get("occurred_at")) >= instant_sort_key(
                previous.get("occurred_at")
            ):
                self.triage[row["violation_id"]] = row
        self.freshness, self.names = Rows(db, "freshness"), Rows(db, "names")
        for row in iter_jsonl(lake / "gold/evidence_freshness.jsonl", missing_ok=True, base_dir=lake):
            check()
            self.freshness[tuple(str(row.get(k) or "") for k in ("tenant_id", "event_id", "asset_id"))] = row
        for row in iter_jsonl(lake / "gold/asset_risk.jsonl", missing_ok=True, base_dir=lake):
            check()
            if row.get("asset_id") and row.get("asset_name"):
                self.names[asset_name_key(row)] = str(row["asset_name"])
        for row in iter_jsonl(lake / "silver/normalized_events.jsonl", missing_ok=True, base_dir=lake):
            check()
            db.execute("INSERT INTO events(hash,data) VALUES (?,?)", (canonical_sha256(row), encoded(row)))
            account, asset = source_asset_key({**row, "asset_id": row.get("asset_id") or ""})
            db.execute("INSERT OR IGNORE INTO asset_types VALUES (?,?,?)", (account, asset, str(row.get("asset_type"))))

    def events(self):
        for digest, data in self.db.execute("SELECT hash,data FROM events ORDER BY hash,ordinal"):
            self.check()
            yield digest, json.loads(data)

    def types(self, account, asset):
        return {
            r[0] for r in self.db.execute("SELECT type FROM asset_types WHERE account=? AND asset=?", (account, asset))
        }

    def evidence(self, account, event, asset, identity):
        self.db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?,?)", (account, encoded(event), asset, identity))

    def get(self, key, default=None):
        account, event, asset = key
        # Repository context only tests whether matching normalized evidence exists.
        row = self.db.execute(
            "SELECT id FROM evidence WHERE account=? AND event=? AND asset=? LIMIT 1", (account, encoded(event), asset)
        ).fetchone()
        return [row[0]] if row else default

    def finding(self, control, identity, severity):
        self.db.execute("INSERT OR IGNORE INTO findings VALUES (?,?,?)", (control, identity, severity))

    def summaries(self, limit):
        for control, count in self.db.execute(
            "SELECT control,count(*) FROM findings GROUP BY control ORDER BY control"
        ):
            yield (
                control,
                count,
                [
                    row[0]
                    for row in self.db.execute(
                        "SELECT id FROM findings WHERE control=? ORDER BY severity,id LIMIT ?", (control, limit)
                    )
                ],
            )

    def drop(self):
        self.db.executescript(
            "DROP TABLE objects; DROP TABLE events; DROP TABLE asset_types; DROP TABLE evidence; DROP TABLE findings;"
        )
