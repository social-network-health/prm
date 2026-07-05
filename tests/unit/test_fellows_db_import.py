#!/usr/bin/env python3
"""The fellows_local_db import path — the first PNA-to-PNA source, with an
ultimate-source provenance chain (SH-7 shape).

A fellows_local_db shared DB carries its contact mirror in a ``fellows`` table
and its provenance chain in-band in a ``provenance`` table (hop 0 = "EHF
Fellows Directory (Knack), archived 2026-04-08"). These tests pin:

  * detection (SQLite magic + ``fellows``-table sniff; a random SQLite file is
    not claimed) and source inference;
  * field mapping + identity (``record_id`` -> UID -> a re-import-stable key);
  * per-field provenance ``observed_at`` = the chain's archive date;
  * chain persistence at ingest: upstream hops preserved verbatim, PRM's own
    hop appended with the consumed file's sha256 (computed at ingest — the
    artifact cannot carry its own hash);
  * the chain-less (pre-provenance) artifact: hop 0 stays the artifact's
    system, never PRM — the importer must not claim to be the ultimate source;
  * the daemon /api/status exposure the workspace origin line renders from.

The fixture DB is generated in-test from the fellows shared-DB schema (the
real fellows.db is private data and never in a repo).

    pytest tests/unit/test_fellows_db_import.py
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from cli import ingest as ingest_mod  # noqa: E402
from cli.config import resolve_home  # noqa: E402
from cli.normalize import normalize_all  # noqa: E402
from cli.parsers import fellows_db  # noqa: E402
from cli.parsers.base import SourceFormat, detect_format  # noqa: E402
from core import shared_db  # noqa: E402
from daemon import server as daemon_server  # noqa: E402

ARCHIVED = "2026-04-08"

_FELLOWS_DDL = """
CREATE TABLE fellows (
    record_id TEXT PRIMARY KEY, slug TEXT NOT NULL, name TEXT, bio_tagline TEXT,
    fellow_type TEXT, cohort TEXT, contact_email TEXT, key_links TEXT,
    key_links_urls TEXT, image_url TEXT, currently_based_in TEXT, search_tags TEXT,
    fellow_status TEXT, gender_pronouns TEXT, ethnicity TEXT, primary_citizenship TEXT,
    global_regions_currently_based_in TEXT, has_image INTEGER NOT NULL DEFAULT 0,
    extra_json TEXT
);
CREATE TABLE provenance (
    hop INTEGER PRIMARY KEY, system TEXT NOT NULL, artifact TEXT,
    artifact_sha256 TEXT, acquired_at TEXT, method TEXT, note TEXT
);
"""

_ROWS = [
    {"record_id": "rec_ada", "slug": "ada_lovelace", "name": "Ada Lovelace",
     "bio_tagline": "First programmer", "fellow_type": "Fellow", "cohort": "Cohort 1",
     "contact_email": "ada@example.org",
     "key_links_urls": json.dumps(["https://example.org/ada"]),
     "currently_based_in": "London",
     "extra_json": json.dumps({"mobile_number": "+44 555 0100"})},
    {"record_id": "rec_grace", "slug": "grace_hopper", "name": "Grace Hopper",
     "fellow_type": "Fellow", "cohort": "Cohort 2"},
]


def _make_fellows_db(dirpath: Path, *, with_chain: bool = True,
                     name: str = "fellows.db") -> Path:
    db = dirpath / name
    con = sqlite3.connect(db)
    con.executescript(_FELLOWS_DDL)
    for row in _ROWS:
        cols = ", ".join(row)
        con.execute(f"INSERT INTO fellows ({cols}) VALUES ({', '.join('?' * len(row))})",
                    tuple(row.values()))
    if with_chain:
        con.execute(
            "INSERT INTO provenance VALUES (0, 'EHF Fellows Directory (Knack)', "
            "'knack_api_detail_dump.json', ?, ?, 'Knack REST API extraction', NULL)",
            ("a" * 64, ARCHIVED))
        con.execute(
            "INSERT INTO provenance VALUES (1, 'fellows_local_db', 'fellows.db', "
            "NULL, NULL, 'build/restore_from_knack_scrapefile.py', NULL)")
    con.commit()
    con.close()
    return db


# ------------------------------------------------------------------ detection
def test_detect_fellows_db_by_magic_and_table():
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_fellows_db(Path(tmp))
        assert detect_format(db) is SourceFormat.FELLOWS_DB
        assert ingest_mod.infer_source(db, SourceFormat.FELLOWS_DB) == ("fellows_local_db", "high")


def test_random_sqlite_and_non_sqlite_db_are_not_claimed():
    with tempfile.TemporaryDirectory() as tmp:
        other = Path(tmp) / "other.db"
        con = sqlite3.connect(other)
        con.execute("CREATE TABLE widgets (id INTEGER)")
        con.commit()
        con.close()
        assert detect_format(other) is SourceFormat.UNKNOWN
        junk = Path(tmp) / "junk.db"
        junk.write_bytes(b"not a database")
        assert detect_format(junk) is SourceFormat.UNKNOWN


# ------------------------------------------------------------------ parsing + identity
def test_parse_maps_fields_and_reads_chain():
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_fellows_db(Path(tmp))
        records, chain = fellows_db.parse(db)
        assert [h["hop"] for h in chain] == [0, 1]
        assert chain[0]["system"] == "EHF Fellows Directory (Knack)"
        assert chain[0]["acquired_at"] == ARCHIVED

        ada = next(r for r in records if r.get("UID").value == "rec_ada")
        assert ada.get("FN").value == "Ada Lovelace"
        assert ada.get("EMAIL").value == "ada@example.org"
        assert ada.get("TEL").value == "+44 555 0100"
        assert ada.get("URL").value == "https://example.org/ada"
        assert ada.get("NOTE").value == "First programmer"
        assert ada.get("X-EHF-COHORT").value == "Cohort 1"
        assert ada.get("REV").value == ARCHIVED   # -> per-field observed_at

        contacts = normalize_all(records)
        by_uid = {c.source_uid: c for c in contacts}
        # record_id is the fellows contract's stable id -> the UID rung.
        assert by_uid["rec_ada"].stable_key.as_str() == "uid:rec_ada"
        assert all(p.observed_at == ARCHIVED for p in by_uid["rec_ada"].provenance)


def test_parse_pre_provenance_db_yields_empty_chain():
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_fellows_db(Path(tmp), with_chain=False)
        con = sqlite3.connect(db)
        con.execute("DROP TABLE provenance")
        con.commit()
        con.close()
        records, chain = fellows_db.parse(db)
        assert chain == []
        assert records and records[0].get("REV") is None


# ------------------------------------------------------------------ ingest end-to-end
def test_ingest_persists_records_and_appends_prm_hop():
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_fellows_db(Path(tmp))
        home = resolve_home(Path(tmp) / "h")
        report = ingest_mod.ingest([db], home=home, dry_run=False)
        assert report.persisted and report.stored == 2
        assert report.by_source == {"fellows_local_db": 2}

        chain = shared_db.source_chain(home.shared_db, "fellows_local_db")
        assert [h["hop"] for h in chain] == [0, 1, 2]
        # Upstream hops preserved verbatim (SH-7: preserve, never rewrite)...
        assert chain[0]["system"] == "EHF Fellows Directory (Knack)"
        assert chain[0]["artifact_sha256"] == "a" * 64
        assert chain[1]["system"] == "fellows_local_db"
        assert chain[1]["artifact_sha256"] is None
        # ...and PRM's own hop appended, carrying the consumed file's sha256
        # computed at ingest (closing the artifact's cannot-self-hash gap).
        assert chain[2]["system"] == "prm"
        assert chain[2]["artifact"] == "fellows.db"
        assert chain[2]["artifact_sha256"] == hashlib.sha256(db.read_bytes()).hexdigest()
        assert chain[2]["acquired_at"]  # the import event's timestamp

        # Per-field provenance carries the archive date, not the ingest date.
        rec = shared_db.all_records(home.shared_db)[0]
        assert all(p["observed_at"] == ARCHIVED for p in rec["provenance"])


def test_chainless_artifact_never_records_prm_as_ultimate_source():
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_fellows_db(Path(tmp), with_chain=False)
        con = sqlite3.connect(db)
        con.execute("DROP TABLE provenance")
        con.commit()
        con.close()
        home = resolve_home(Path(tmp) / "h")
        ingest_mod.ingest([db], home=home, dry_run=False)
        chain = shared_db.source_chain(home.shared_db, "fellows_local_db")
        assert [h["hop"] for h in chain] == [0, 1]
        assert chain[0]["system"] == "fellows_local_db"     # the artifact's own system
        assert "no in-band provenance" in (chain[0]["note"] or "")
        assert chain[1]["system"] == "prm"


def test_reingest_is_idempotent_and_refreshes_chain():
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_fellows_db(Path(tmp))
        home = resolve_home(Path(tmp) / "h")
        ingest_mod.ingest([db], home=home, dry_run=False)
        first = {r["id"] for r in shared_db.all_records(home.shared_db)}
        ingest_mod.ingest([db], home=home, dry_run=False)
        again = {r["id"] for r in shared_db.all_records(home.shared_db)}
        assert first == again                                   # re-attach, no duplicates
        chain = shared_db.source_chain(home.shared_db, "fellows_local_db")
        assert [h["hop"] for h in chain] == [0, 1, 2]           # replaced, not appended twice


# ------------------------------------------------------------------ daemon exposure
def test_status_exposes_source_chains():
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_fellows_db(Path(tmp))
        home = resolve_home(Path(tmp) / "h")
        ingest_mod.ingest([db], home=home, dry_run=False)
        status, ctype, body = daemon_server.route("GET", "/api/status", {}, home)
        assert status == 200
        payload = json.loads(body)
        chains = payload["source_chains"]
        assert "fellows_local_db" in chains
        assert chains["fellows_local_db"][0]["system"] == "EHF Fellows Directory (Knack)"
        assert chains["fellows_local_db"][-1]["system"] == "prm"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
