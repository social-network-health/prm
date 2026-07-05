#!/usr/bin/env python3
"""shared.db schema v2 — the ``source_chains`` table (ultimate-source provenance, SH-7 shape).

Pins the additive v1 -> v2 migration (a v1 db upgrades in place, keeping its rows), the
record/read round-trip, replace-not-append idempotency, and the pre-v2 read tolerance.

    pytest tests/db/test_source_chains.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core import shared_db  # noqa: E402

_HOPS = [
    {"hop": 0, "system": "EHF Fellows Directory (Knack)", "artifact": "dump.json",
     "artifact_sha256": "a" * 64, "acquired_at": "2026-04-08",
     "method": "Knack REST API extraction", "note": None},
    {"hop": 1, "system": "prm", "artifact": "fellows.db", "artifact_sha256": "b" * 64,
     "acquired_at": "2026-07-05T00:00:00Z", "method": "cli/ingest.py", "note": None},
]


def test_record_and_read_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "shared.db"
        shared_db.record_source_chain(db, "fellows_local_db", _HOPS)
        chain = shared_db.source_chain(db, "fellows_local_db")
        assert chain == _HOPS
        assert shared_db.all_source_chains(db) == {"fellows_local_db": _HOPS}
        assert shared_db.source_chain(db, "google_takeout") == []


def test_record_replaces_not_appends():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "shared.db"
        shared_db.record_source_chain(db, "fellows_local_db", _HOPS)
        shorter = _HOPS[:1]
        shared_db.record_source_chain(db, "fellows_local_db", shorter)
        assert shared_db.source_chain(db, "fellows_local_db") == shorter


def test_v1_db_migrates_in_place_keeping_rows():
    """A schema-v1 shared.db (pre-source_chains) upgrades additively on the next
    write path: user_version moves to 2, existing rows survive, and the new
    table exists. This is what lets an existing PRM home accept a
    provenance-carrying import without a rebuild."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "shared.db"
        con = sqlite3.connect(db)
        # Minimal v1 shape: the three v1 tables, stamped user_version=1.
        con.executescript("""
            CREATE TABLE source_records (
                source_record_id TEXT PRIMARY KEY, source TEXT NOT NULL,
                source_uid TEXT, stable_key TEXT NOT NULL,
                ingested_at TEXT NOT NULL, raw_jcard TEXT NOT NULL);
            CREATE TABLE field_provenance (
                source_record_id TEXT NOT NULL, field TEXT NOT NULL,
                value TEXT NOT NULL, observed_at TEXT);
            CREATE VIRTUAL TABLE contacts_fts USING fts5(
                source_record_id UNINDEXED, name, email, org, title, note);
        """)
        con.execute("INSERT INTO source_records VALUES ('id1', 'vcard', NULL, 'uid:x', 't', '[]')")
        con.execute("PRAGMA user_version = 1")
        con.commit()
        con.close()

        shared_db.record_source_chain(db, "fellows_local_db", _HOPS[:1])

        con = sqlite3.connect(db)
        assert con.execute("PRAGMA user_version").fetchone()[0] == shared_db.SCHEMA_VERSION
        assert con.execute("SELECT count(*) FROM source_records").fetchone()[0] == 1
        con.close()
        assert shared_db.source_chain(db, "fellows_local_db") == _HOPS[:1]


def test_pre_v2_read_tolerance():
    """Read helpers return empty on a db whose file predates source_chains
    (opened read-only, so no migration can run)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "shared.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE source_records (source_record_id TEXT PRIMARY KEY)")
        con.commit()
        con.close()
        assert shared_db.source_chain(db, "anything") == []
        assert shared_db.all_source_chains(db) == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
