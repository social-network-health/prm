"""core/groups.py — user-curated contact sets (the groups private layer, schema v4).

PNT PR-1's ``groups`` + ``group_members``, adapted to PRM: membership keys on the **canonical
contact_id** (the projection's entity), not the raw record_id, and the merge apply re-points it at the
surviving contact so a group survives dedup (see ``relationships_db.apply_operations``). Groups are
authored **only** in the workspace — the MCP surface is read-only over groups and exposes no group-write
tool, the same structural lock as INV-3 — and each group carries a PR-7 ``disclosure_tier`` defaulting
to sealed. Rationale: ``plans/groups-and-tags.md``.

A leaf over ``relationships_db`` (no ``cli`` / sibling imports). Writers are serialized by the caller
(``core/apply.py`` holds the AC-PRM-C file-lock and audits; destructive ops snapshot first).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from core import relationships_db

GROUP_COLS = ("group_id", "name", "note", "disclosure_tier", "created_at", "updated_at")
DISCLOSURE_TIERS = {"private-sealed", "private-shareable-on-consent"}
_MUTABLE = ("name", "note", "disclosure_tier")


class GroupError(ValueError):
    """A group authoring rule was violated (missing group, duplicate name, bad tier, …)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(r) -> dict:
    return dict(zip(GROUP_COLS, r))


def _name_taken(con, name: str, *, except_id: str | None = None) -> bool:
    row = con.execute("SELECT group_id FROM groups WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    return bool(row and row[0] != except_id)


# --------------------------------------------------------------------------- read
def list_groups(db_path) -> list[dict]:
    """Every group with its ``member_count``, most-recently-updated first (the PNT contract's order)."""
    if not Path(db_path).exists():
        return []
    con = relationships_db.connect(db_path, read_only=True)
    try:
        rows = con.execute(
            f"SELECT {', '.join('g.' + c for c in GROUP_COLS)}, count(m.contact_id) "
            "FROM groups g LEFT JOIN group_members m USING (group_id) "
            "GROUP BY g.group_id ORDER BY g.updated_at DESC, g.name COLLATE NOCASE"
        ).fetchall()
    finally:
        con.close()
    return [{**_row(r[:-1]), "member_count": r[-1]} for r in rows]


def get_group(db_path, group_id: str) -> dict | None:
    """One group with its member contact_ids (insertion-ordered), or ``None``."""
    if not Path(db_path).exists():
        return None
    con = relationships_db.connect(db_path, read_only=True)
    try:
        row = con.execute(f"SELECT {', '.join(GROUP_COLS)} FROM groups WHERE group_id = ?",
                          (group_id,)).fetchone()
        if row is None:
            return None
        members = [cid for (cid,) in con.execute(
            "SELECT contact_id FROM group_members WHERE group_id = ? ORDER BY added_at, contact_id",
            (group_id,))]
    finally:
        con.close()
    return {**_row(row), "member_ids": members, "member_count": len(members)}


def find_group(db_path, name: str) -> dict | None:
    """One group by exact (case-insensitive) name, or ``None`` — the CLI ``--group <name>`` resolver."""
    if not Path(db_path).exists():
        return None
    con = relationships_db.connect(db_path, read_only=True)
    try:
        row = con.execute("SELECT group_id FROM groups WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    finally:
        con.close()
    return get_group(db_path, row[0]) if row else None


def groups_for_contact(db_path, contact_id: str) -> list[dict]:
    """The groups a contact belongs to (for the contact-detail chips), name-ordered."""
    if not Path(db_path).exists():
        return []
    con = relationships_db.connect(db_path, read_only=True)
    try:
        rows = con.execute(
            f"SELECT {', '.join('g.' + c for c in GROUP_COLS)} FROM groups g "
            "JOIN group_members m USING (group_id) WHERE m.contact_id = ? ORDER BY g.name COLLATE NOCASE",
            (contact_id,)).fetchall()
    finally:
        con.close()
    return [_row(r) for r in rows]


def all_memberships(db_path) -> dict:
    """{contact_id: [group_id, …]} for every membership — the projection/list-view bulk source."""
    if not Path(db_path).exists():
        return {}
    con = relationships_db.connect(db_path, read_only=True)
    try:
        rows = con.execute("SELECT contact_id, group_id FROM group_members").fetchall()
    finally:
        con.close()
    out: dict[str, list] = {}
    for cid, gid in rows:
        out.setdefault(cid, []).append(gid)
    return out


# --------------------------------------------------------------------------- write (workspace-only)
def create_group(db_path, name: str, *, note: str = "") -> dict:
    """Create a group. Names are unique case-insensitively (so ``find_group`` / ``--group`` stay
    unambiguous); the id is opaque because groups are renameable."""
    name = (name or "").strip()
    if not name:
        raise GroupError("a group needs a name")
    relationships_db.ensure(db_path)
    con = relationships_db.connect(db_path)
    try:
        if _name_taken(con, name):
            raise GroupError(f"a group named {name!r} already exists")
        gid = "g-" + uuid.uuid4().hex[:12]
        now = _now_iso()
        con.execute("INSERT INTO groups(group_id, name, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (gid, name, note or "", now, now))
        con.commit()
    finally:
        con.close()
    return get_group(db_path, gid)


def update_group(db_path, group_id: str, **changes) -> dict:
    """Edit a group's mutable attributes (``name`` / ``note`` / ``disclosure_tier``)."""
    bad = set(changes) - set(_MUTABLE)
    if bad:
        raise GroupError(f"cannot change {sorted(bad)} (immutable or unknown)")
    if "disclosure_tier" in changes and changes["disclosure_tier"] not in DISCLOSURE_TIERS:
        raise GroupError(f"unknown disclosure_tier: {changes['disclosure_tier']!r}")
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
        if not changes["name"]:
            raise GroupError("a group needs a name")
    con = relationships_db.connect(db_path)
    try:
        if not con.execute("SELECT 1 FROM groups WHERE group_id = ?", (group_id,)).fetchone():
            raise GroupError(f"no such group: {group_id!r}")
        if "name" in changes and _name_taken(con, changes["name"], except_id=group_id):
            raise GroupError(f"a group named {changes['name']!r} already exists")
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes) + ", updated_at = ?"
            con.execute(f"UPDATE groups SET {sets} WHERE group_id = ?",
                        [*changes.values(), _now_iso(), group_id])
            con.commit()
    finally:
        con.close()
    return get_group(db_path, group_id)


def delete_group(db_path, group_id: str) -> None:
    """Delete a group (its memberships cascade). The caller snapshots first — this is destructive."""
    con = relationships_db.connect(db_path)
    try:
        if not con.execute("SELECT 1 FROM groups WHERE group_id = ?", (group_id,)).fetchone():
            raise GroupError(f"no such group: {group_id!r}")
        con.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
        con.commit()
    finally:
        con.close()


def add_members(db_path, group_id: str, contact_ids) -> dict:
    """Add contacts to a group. Idempotent (already-members are no-ops). A contact_id that doesn't
    resolve is **reported, not silently dropped** — returns ``{"added": n, "unknown": [...]}``."""
    contact_ids = list(dict.fromkeys(contact_ids or []))
    con = relationships_db.connect(db_path)
    try:
        if not con.execute("SELECT 1 FROM groups WHERE group_id = ?", (group_id,)).fetchone():
            raise GroupError(f"no such group: {group_id!r}")
        qs = ",".join("?" * len(contact_ids)) or "''"
        known = {cid for (cid,) in con.execute(
            f"SELECT contact_id FROM contacts WHERE contact_id IN ({qs})", contact_ids)}
        unknown = [cid for cid in contact_ids if cid not in known]
        now, added = _now_iso(), 0
        for cid in contact_ids:
            if cid in known:
                cur = con.execute("INSERT OR IGNORE INTO group_members(group_id, contact_id, added_at) "
                                  "VALUES (?, ?, ?)", (group_id, cid, now))
                added += cur.rowcount
        if added:
            con.execute("UPDATE groups SET updated_at = ? WHERE group_id = ?", (now, group_id))
        con.commit()
    finally:
        con.close()
    return {"added": added, "unknown": unknown}


def remove_members(db_path, group_id: str, contact_ids) -> int:
    """Remove contacts from a group; returns how many rows went away. The caller snapshots first."""
    contact_ids = list(dict.fromkeys(contact_ids or []))
    if not contact_ids:
        return 0
    con = relationships_db.connect(db_path)
    try:
        if not con.execute("SELECT 1 FROM groups WHERE group_id = ?", (group_id,)).fetchone():
            raise GroupError(f"no such group: {group_id!r}")
        qs = ",".join("?" * len(contact_ids))
        cur = con.execute(f"DELETE FROM group_members WHERE group_id = ? AND contact_id IN ({qs})",
                          (group_id, *contact_ids))
        removed = cur.rowcount
        if removed:
            con.execute("UPDATE groups SET updated_at = ? WHERE group_id = ?", (_now_iso(), group_id))
        con.commit()
    finally:
        con.close()
    return removed
