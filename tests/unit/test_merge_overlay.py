#!/usr/bin/env python3
"""Merge survivorship for the WHOLE private overlay (issue #88): a merge must never silently drop the
losing contact's relationship data. Every overlay table cascades on the losing ``contacts`` row's
delete, so each needs decided merge semantics:

- ``field_values`` (tags / notes / photo / custom) — re-pointed to the survivor with recomputed ids:
  multi-valued fields union (identical values collapse); single-valued values COEXIST as rows (the
  already-sanctioned append-only state) and the user consolidates in Edit.
- ``observations`` — re-pointed; a loser's ``accepted`` observation is demoted to ``observed`` (its
  promote-written resolution died with the loser, so it returns to pending review on the survivor);
  ``rejected`` stays rejected (won't resurface); the loser's ``superseded`` one-deep previous is dropped.
- ``group_members`` — re-pointed (pinned in test_groups.py).
- ``field_resolutions`` — cascades BY DESIGN (the survivor's conflicts are re-resolved in the merge UI).

The category guard at the bottom fails the suite the moment a new table references contacts(contact_id)
without its merge semantics being decided here and implemented in ``apply_operations``.

    python tests/unit/test_merge_overlay.py
    pytest tests/unit/test_merge_overlay.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from cli import ingest as ingest_mod  # noqa: E402
from cli.config import resolve_home  # noqa: E402
from core import apply, media, projection, relationships_db  # noqa: E402

FIX = REPO / "tests" / "fixtures"
APPLE = FIX / "apple_icloud" / "sources" / "icloud-export.vcf"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d494844520000000100000001080600000"
                    "01f15c4890000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")


def _apple_home(tmp: str):
    home = resolve_home(Path(tmp) / "h")
    ingest_mod.ingest([APPLE], home=home, dry_run=False)   # 4 contacts, 1:1 baseline
    return home


def _ids(home, n):
    return list(relationships_db.identity_map(home.relationships_db))[:n]


def _merge(home, loser, survivor):
    cs = apply.build_merge_changeset(home, [survivor, loser], survivor, created_by="manual:test")
    apply.apply_changeset(home, cs)


def _values(home, cid, fid):
    return sorted(v["value"] for v in relationships_db.field_values_for(home.relationships_db, cid)
                  if v["field_id"] == fid)


# ------------------------------------------------------------------ field_values
def test_merge_unions_tags_without_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        apply.set_field_value(home, a, "tags", "work")
        apply.set_field_value(home, a, "tags", "friend")     # shared tag — must collapse, not duplicate
        apply.set_field_value(home, b, "tags", "family")
        apply.set_field_value(home, b, "tags", "friend")

        _merge(home, loser=b, survivor=a)
        assert _values(home, a, "tags") == ["family", "friend", "work"]


def test_merge_keeps_both_notes():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        apply.set_field_value(home, a, "notes", "met at the conference")
        apply.set_field_value(home, b, "notes", "prefers email")

        _merge(home, loser=b, survivor=a)
        # single-valued values COEXIST (like an append-only write) — nothing is silently discarded;
        # the detail view shows both and an Edit-save consolidates to one.
        assert _values(home, a, "notes") == ["met at the conference", "prefers email"]


def test_merge_adopts_loser_photo():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        h = media.put(home, PNG, mime="image/png")
        apply.set_field_value(home, b, "photo", h)           # only the LOSER has an avatar

        _merge(home, loser=b, survivor=a)
        assert _values(home, a, "photo") == [h]
        got = projection.contact_photo(home, a)
        assert got and got[0] == PNG                         # the survivor's avatar now resolves


def test_merge_preserves_custom_field_values():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        apply.define_field(home, label="How we met", kind="text")
        apply.set_field_value(home, b, "how_we_met", "through Carol")

        _merge(home, loser=b, survivor=a)
        assert _values(home, a, "how_we_met") == ["through Carol"]


# ------------------------------------------------------------------ observations
def test_merge_preserves_observations_and_demotes_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        pending = apply.observe_field(home, b, "url", "https://x.example", written_by="ai:t", source="web")
        rejected = apply.observe_field(home, b, "nickname", "Bee", written_by="ai:t", source="web")
        apply.reject_observation(home, rejected["obs_id"])
        accepted = apply.observe_field(home, b, "org", "Acme", written_by="ai:t", source="web")
        apply.promote_observation(home, accepted["obs_id"])  # single-valued → wrote b's resolution

        _merge(home, loser=b, survivor=a)
        obs = {(o["field"], o["value"]): o["status"]
               for o in relationships_db.observations_for(home.relationships_db, a)}
        assert obs[("url", "https://x.example")] == "observed"      # pending survives as pending
        assert obs[("nickname", "Bee")] == "rejected"               # a dismissal never resurfaces
        # the loser's ACCEPTED observation returns to pending on the survivor: its promote-written
        # resolution died with the loser's contact row, so the user re-reviews it in context.
        assert obs[("org", "Acme")] == "observed"


# ------------------------------------------------------------------ undo + batch
def test_merge_overlay_undo_restores_everything():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        apply.set_field_value(home, b, "tags", "family")
        apply.set_field_value(home, b, "notes", "prefers email")

        _merge(home, loser=b, survivor=a)
        assert apply.undo(home)
        assert _values(home, b, "tags") == ["family"]
        assert _values(home, b, "notes") == ["prefers email"]
        assert _values(home, a, "tags") == []


def test_batch_merge_preserves_overlay():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b, c, d = _ids(home, 4)
        apply.set_field_value(home, b, "tags", "family")
        apply.set_field_value(home, d, "notes", "old colleague")

        res = apply.apply_batch(home, [
            {"kind": "candidate", "member_ids": [a, b], "into": a},
            {"kind": "candidate", "member_ids": [c, d], "into": c}])
        assert res["ok"] and res["merged"] == 2
        assert _values(home, a, "tags") == ["family"]
        assert _values(home, c, "notes") == ["old colleague"]


# ------------------------------------------------------------------ the category guard
# Every table with an FK to contacts(contact_id) cascades when a merge deletes the losing contact row.
# A new table in that set MUST have its merge semantics decided in apply_operations' merge branch and
# recorded here — otherwise this test fails and the suite stays red until it's handled. That is the
# point: issue #88 happened because field_values/observations joined the schema after the merge code.
_MERGE_SEMANTICS = {
    "identity_map": "re-pointed at the survivor (the merge itself)",
    "field_resolutions": "cascades BY DESIGN — survivor conflicts are re-resolved via the merge UI's picks",
    "field_values": "re-pointed with recomputed value_ids (union; single-valued values coexist)",
    "observations": "re-pointed with recomputed obs_ids (accepted→observed; superseded dropped; rejected kept)",
    "group_members": "re-pointed at the survivor (INSERT OR IGNORE collapse)",
}


def test_every_contacts_fk_table_has_decided_merge_semantics():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "relationships.db"
        relationships_db.ensure(db)
        con = relationships_db.connect(db, read_only=True)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            referencing = {t for t in tables
                           for fk in con.execute(f"PRAGMA foreign_key_list({t})") if fk[2] == "contacts"}
        finally:
            con.close()
        assert referencing == set(_MERGE_SEMANTICS), (
            f"tables referencing contacts(contact_id) changed: {sorted(referencing)} vs decided "
            f"{sorted(_MERGE_SEMANTICS)}. A cascade on the losing contact's delete silently destroys "
            f"rows (issue #88) — decide the new table's merge semantics in "
            f"relationships_db.apply_operations (merge branch), pin it with a test above, then record "
            f"it in _MERGE_SEMANTICS."
        )


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = []
    for t in tests:
        try:
            t()
            print(f"[OK]   {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures.append(t.__name__)
            print(f"[FAIL] {t.__name__}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
