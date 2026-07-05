"""fellows_local_db parser: another PNA's shared SQLite DB -> ``ParsedRecord``s + provenance chain.

The first PNA-to-PNA import path. fellows_local_db (the sibling Directory Archive reference design)
ships its contact mirror as a single SQLite file whose ``fellows`` table holds one row per person and
whose in-band ``provenance`` table carries the dataset's **ultimate-source chain** (hop 0 = "EHF
Fellows Directory (Knack), archived 2026-04-08"; see the staged PNT sub-contract SH-7 in
fellows_local_db ``plans/pna_toolkit_provenance_chain_contribution.md``). We read both: rows become
contacts, the chain becomes this source's ``source_chains`` entry — with PRM's own hop appended by
the ingester, never here (the parser reports what the file *claims*; the import event is the
ingester's fact to record).

Identity: ``record_id`` is the fellows shared-DB contract's opaque, re-mirror-stable primary key, so
it maps to ``UID`` and the stable-key fallback chain stops at its strongest rung — a fellows
re-export re-attaches to the same ``source_record_id``.

Provenance timestamps: every field's ``observed_at`` is the chain's hop-0 ``acquired_at`` (the
archive date) — that is when the source system last vouched for these values. A chain-less
(pre-provenance) fellows.db yields ``observed_at=None`` and the ingest time backfills, same as any
other source.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .base import ParsedRecord, RawField

SOURCE = "fellows_local_db"

_CHAIN_COLS = ("hop", "system", "artifact", "artifact_sha256", "acquired_at", "method", "note")


def read_chain(con: sqlite3.Connection) -> list[dict]:
    """The in-band provenance chain, hop-ordered; [] for a pre-provenance fellows.db."""
    try:
        rows = con.execute(
            f"SELECT {', '.join(_CHAIN_COLS)} FROM provenance ORDER BY hop"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(zip(_CHAIN_COLS, r)) for r in rows]


def _extra(row: dict) -> dict:
    try:
        return json.loads(row.get("extra_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _record_fields(row: dict, extra: dict, observed_at: str | None) -> list[RawField]:
    fields: list[RawField] = [RawField("UID", row["record_id"])]
    if observed_at:
        # Consumed by normalize as the per-field provenance timestamp (like vCard REV).
        fields.append(RawField("REV", observed_at))
    if row.get("name"):
        fields.append(RawField("FN", row["name"]))
    if row.get("contact_email"):
        fields.append(RawField("EMAIL", row["contact_email"]))
    mobile = (extra.get("mobile_number") or "").strip()
    if mobile:
        fields.append(RawField("TEL", mobile))
    for url in _key_link_urls(row):
        fields.append(RawField("URL", url))
    if row.get("bio_tagline"):
        fields.append(RawField("NOTE", row["bio_tagline"]))
    # Fellows-specific display columns ride as X- properties (kept, searchable
    # via note only when promoted later; never guessed into org/title semantics).
    for col, prop in (("cohort", "X-EHF-COHORT"),
                      ("fellow_type", "X-EHF-FELLOW-TYPE"),
                      ("currently_based_in", "X-EHF-BASED-IN"),
                      ("slug", "X-EHF-SLUG")):
        val = (row.get(col) or "").strip()
        if val:
            fields.append(RawField(prop, val))
    return fields


def _key_link_urls(row: dict) -> list[str]:
    raw = row.get("key_links_urls")
    if not raw:
        return []
    try:
        urls = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [u for u in urls if isinstance(u, str) and u.strip()]


def parse(path: str | Path, source: str = SOURCE) -> tuple[list[ParsedRecord], list[dict]]:
    """Parse a fellows_local_db shared DB. Returns (records, chain).

    Raises ``ValueError`` on a file without the expected ``fellows`` table so
    the ingester can skip it with a reason (same contract as the CSV parser).
    """
    p = Path(path)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        chain = read_chain(con)
        try:
            rows = con.execute("SELECT * FROM fellows ORDER BY record_id").fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError(f"not a fellows_local_db shared DB: {exc}") from exc
    finally:
        con.close()

    observed_at = chain[0].get("acquired_at") if chain else None
    records: list[ParsedRecord] = []
    for r in rows:
        row = dict(r)
        if not (row.get("record_id") or "").strip():
            continue
        extra = _extra(row)
        records.append(ParsedRecord(
            source=source,
            fields=_record_fields(row, extra, observed_at),
            raw_text=json.dumps({k: v for k, v in row.items() if v not in (None, "")},
                                ensure_ascii=False, sort_keys=True),
        ))
    return records, chain
