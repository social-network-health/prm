#!/usr/bin/env python3
"""Tests for the groups private layer (schema v4, plans/groups-and-tags.md): CRUD + membership over
core/groups.py, the merge-survivorship guarantee (a merge re-points group_members at the survivor —
the FK cascade must never silently drop a membership), undo, the v3→v4 migration, and the audited
apply-path wrappers.

    python tests/unit/test_groups.py
    pytest tests/unit/test_groups.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from cli import ingest as ingest_mod  # noqa: E402
from cli.config import resolve_home  # noqa: E402
from core import apply, audit, groups, relationships_db, snapshots  # noqa: E402

FIX = REPO / "tests" / "fixtures"
APPLE = FIX / "apple_icloud" / "sources" / "icloud-export.vcf"


def _apple_home(tmp: str):
    home = resolve_home(Path(tmp) / "h")
    ingest_mod.ingest([APPLE], home=home, dry_run=False)   # 4 contacts, 1:1 baseline
    return home


def _ids(home, n):
    return list(relationships_db.identity_map(home.relationships_db))[:n]


# ------------------------------------------------------------------ CRUD
def test_create_list_get_update_delete():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        db = home.relationships_db
        g = groups.create_group(db, "Emergency contacts", note="who to call")
        assert g["name"] == "Emergency contacts" and g["note"] == "who to call"
        assert g["disclosure_tier"] == "private-sealed"            # sealed by default (PR-7)
        assert g["member_ids"] == [] and g["member_count"] == 0

        # duplicate names refused case-insensitively (keeps find_group / --group unambiguous)
        try:
            groups.create_group(db, "emergency CONTACTS")
            raise AssertionError("expected GroupError for a duplicate name")
        except groups.GroupError:
            pass

        assert groups.find_group(db, "EMERGENCY contacts")["group_id"] == g["group_id"]
        assert [x["group_id"] for x in groups.list_groups(db)] == [g["group_id"]]

        g2 = groups.update_group(db, g["group_id"], name="ICE", note="")
        assert g2["name"] == "ICE" and g2["note"] == ""
        try:
            groups.update_group(db, g["group_id"], created_at="2020-01-01")  # immutable
            raise AssertionError("expected GroupError for an immutable attribute")
        except groups.GroupError:
            pass

        groups.delete_group(db, g["group_id"])
        assert groups.get_group(db, g["group_id"]) is None
        assert groups.list_groups(db) == []


# ------------------------------------------------------------------ membership
def test_membership_add_remove_and_unknown_reported():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        db = home.relationships_db
        a, b = _ids(home, 2)
        g = groups.create_group(db, "Friends")

        res = groups.add_members(db, g["group_id"], [a, b, a, "nope-not-a-contact"])
        assert res["added"] == 2                                    # dupes are no-ops
        assert res["unknown"] == ["nope-not-a-contact"]             # reported, never silently dropped
        assert set(groups.get_group(db, g["group_id"])["member_ids"]) == {a, b}
        assert groups.list_groups(db)[0]["member_count"] == 2
        assert [x["name"] for x in groups.groups_for_contact(db, a)] == ["Friends"]
        assert groups.all_memberships(db) == {a: [g["group_id"]], b: [g["group_id"]]}

        assert groups.add_members(db, g["group_id"], [a])["added"] == 0     # idempotent
        assert groups.remove_members(db, g["group_id"], [a]) == 1
        assert groups.get_group(db, g["group_id"])["member_ids"] == [b]

        groups.delete_group(db, g["group_id"])                      # membership cascades with the group
        assert groups.groups_for_contact(db, b) == []


# ------------------------------------------------------------------ merge survivorship (the red test)
def test_merge_repoints_group_membership_at_survivor():
    """A merge must re-point group_members at the surviving contact — the losing contacts row is
    deleted, and without the re-point the FK cascade silently drops the membership (data loss)."""
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        db = home.relationships_db
        a, b, c = _ids(home, 3)
        both = groups.create_group(db, "Both halves")               # contains winner AND loser
        groups.add_members(db, both["group_id"], [a, b])
        only_loser = groups.create_group(db, "Only the loser")      # contains ONLY the loser
        groups.add_members(db, only_loser["group_id"], [b])
        other = groups.create_group(db, "Bystander")                # unrelated contact — untouched
        groups.add_members(db, other["group_id"], [c])

        cs = apply.build_merge_changeset(home, [a, b], a, created_by="manual:test")
        apply.apply_changeset(home, cs)

        assert groups.get_group(db, both["group_id"])["member_ids"] == [a]        # collapsed, not dropped
        assert groups.get_group(db, only_loser["group_id"])["member_ids"] == [a]  # re-pointed at survivor
        assert groups.get_group(db, other["group_id"])["member_ids"] == [c]       # bystander untouched

        assert apply.undo(home)                                     # snapshot-restore reverses it all
        assert set(groups.get_group(db, both["group_id"])["member_ids"]) == {a, b}
        assert groups.get_group(db, only_loser["group_id"])["member_ids"] == [b]


# ------------------------------------------------------------------ re-import survivorship
def test_membership_survives_reimport():
    """Membership keys on the canonical contact_id (seeded from the stable source_record_id), so
    re-importing the same export re-attaches — the group must be untouched (INV-5/6)."""
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        db = home.relationships_db
        a = _ids(home, 1)[0]
        g = groups.create_group(db, "Keepers")
        groups.add_members(db, g["group_id"], [a])

        ingest_mod.ingest([APPLE], home=home, dry_run=False)    # same export again → same stable ids
        assert groups.get_group(db, g["group_id"])["member_ids"] == [a]


# ------------------------------------------------------------------ migration
def test_v3_store_migrates_to_v4():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "relationships.db"
        relationships_db.ensure(db)
        con = relationships_db.connect(db)
        con.execute("DROP TABLE group_members")                     # simulate a pre-groups (v3) store
        con.execute("DROP TABLE groups")
        con.execute("PRAGMA user_version = 3")
        con.commit()
        con.close()

        relationships_db.ensure(db)                                 # the startup migration chokepoint
        assert relationships_db.stats(db)["schema_version"] == 4
        assert groups.list_groups(db) == []                         # the v4 tables exist and are empty


# ------------------------------------------------------------------ the audited apply-path wrappers
def test_apply_wrappers_audit_and_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)

        g = apply.create_group(home, "Team", note="")
        apply.set_group_members(home, g["group_id"], add=[a, b])
        assert audit.read(home)[-1]["kind"] == "group_members"
        assert not snapshots.list_snapshots(home)                   # additive ops don't snapshot

        apply.set_group_members(home, g["group_id"], remove=[b])    # destructive → snapshot first
        assert len(snapshots.list_snapshots(home)) == 1
        assert groups.get_group(home.relationships_db, g["group_id"])["member_ids"] == [a]

        apply.update_group(home, g["group_id"], name="Team A")
        assert audit.read(home)[-1]["kind"] == "group_update"

        apply.delete_group(home, g["group_id"])                     # destructive → snapshot first
        assert len(snapshots.list_snapshots(home)) == 2
        assert groups.get_group(home.relationships_db, g["group_id"]) is None
        assert apply.undo(home)                                     # …and Undo brings the group back
        assert groups.get_group(home.relationships_db, g["group_id"])["name"] == "Team A"


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
