#!/usr/bin/env python3
"""Tests for the daemon's groups + tags API (plans/groups-and-tags.md): GET/POST /api/groups[…],
member hydration (orphan-tolerant), the contact-detail group chips, and GET /api/tags (vocabulary +
counts, orphaned values flagged) — all through the pure ``route()``.

    python tests/unit/test_daemon_groups_api.py
    pytest tests/unit/test_daemon_groups_api.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from cli import ingest as ingest_mod  # noqa: E402
from cli.config import resolve_home  # noqa: E402
from core import apply, relationships_db, schema  # noqa: E402
from daemon import server  # noqa: E402

FIX = REPO / "tests" / "fixtures"
APPLE = FIX / "apple_icloud" / "sources" / "icloud-export.vcf"


def _body(resp) -> dict:
    _, _, body = resp
    return json.loads(body)


def _apple_home(tmp: str):
    home = resolve_home(Path(tmp) / "h")
    ingest_mod.ingest([APPLE], home=home, dry_run=False)
    return home


def _ids(home, n):
    return list(relationships_db.identity_map(home.relationships_db))[:n]


# ------------------------------------------------------------------ groups CRUD over the API
def test_groups_create_list_detail_edit_delete():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)

        status, _, _ = server.route("POST", "/api/groups", {}, home, {"name": ""})
        assert status == 400                                              # a group needs a name
        g = _body(server.route("POST", "/api/groups", {}, home,
                               {"name": "Emergency contacts", "note": "who to call"}))["group"]
        gid = g["group_id"]
        assert g["disclosure_tier"] == "private-sealed"

        status, _, _ = server.route("POST", "/api/groups", {}, home, {"name": "emergency CONTACTS"})
        assert status == 400                                              # duplicate name → GroupError → 400

        listed = _body(server.route("GET", "/api/groups", {}, home))["groups"]
        assert [x["group_id"] for x in listed] == [gid] and listed[0]["member_count"] == 0

        res = _body(server.route("POST", f"/api/groups/{gid}/members", {}, home, {"add": [a, b]}))
        assert res["added"] == 2 and res["unknown"] == []

        detail = _body(server.route("GET", f"/api/groups/{gid}", {}, home))
        assert detail["member_count"] == 2
        assert {m["id"] for m in detail["members"]} == {a, b}
        assert all(m["name"] for m in detail["members"])                  # hydrated display rows

        g2 = _body(server.route("POST", f"/api/groups/{gid}", {}, home, {"name": "ICE"}))["group"]
        assert g2["name"] == "ICE"

        res = _body(server.route("POST", f"/api/groups/{gid}/members", {}, home, {"remove": [b]}))
        assert res["removed"] == 1 and res["snapshot"]                    # removal snapshots (Undo-able)

        assert _body(server.route("POST", f"/api/groups/{gid}/delete", {}, home, {}))["ok"]
        status, _, _ = server.route("GET", f"/api/groups/{gid}", {}, home)
        assert status == 404
        status, _, _ = server.route("POST", "/api/groups/nope/members", {}, home, {"add": [a]})
        assert status == 404                                              # unknown group


# ------------------------------------------------------------------ contact chips + merge behavior
def test_contact_detail_carries_group_chips():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        gid = _body(server.route("POST", "/api/groups", {}, home, {"name": "Friends"}))["group"]["group_id"]
        server.route("POST", f"/api/groups/{gid}/members", {}, home, {"add": [b]})

        detail = _body(server.route("GET", f"/api/contact/{b}", {}, home))
        assert [g["name"] for g in detail["groups"]] == ["Friends"]
        assert _body(server.route("GET", f"/api/contact/{a}", {}, home))["groups"] == []

        # merging the member into another contact re-points the chip at the survivor
        server.route("POST", "/api/merge", {}, home, {"member_ids": [a, b], "into": a})
        detail = _body(server.route("GET", f"/api/contact/{a}", {}, home))
        assert [g["name"] for g in detail["groups"]] == ["Friends"]


# ------------------------------------------------------------------ tags browse
def test_tags_vocabulary_with_counts_and_orphans():
    with tempfile.TemporaryDirectory() as tmp:
        home = _apple_home(tmp)
        a, b = _ids(home, 2)
        schema.update_field(home.relationships_db, "tags", config={"options": [
            {"value": "family", "label": "Family", "description": "kin"},
            {"value": "work", "label": "Work"}]})
        apply.set_field_value(home, a, "tags", "family")
        apply.set_field_value(home, b, "tags", "family")
        apply.set_field_value(home, b, "tags", "stray")          # in use but not in the vocabulary

        tags = _body(server.route("GET", "/api/tags", {}, home))["tags"]
        by_value = {t["value"]: t for t in tags}
        assert by_value["family"]["count"] == 2 and by_value["family"]["description"] == "kin"
        assert by_value["work"]["count"] == 0                    # vocabulary entries show even unused
        assert by_value["stray"]["count"] == 1 and by_value["stray"].get("orphan")   # flagged, not hidden


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
