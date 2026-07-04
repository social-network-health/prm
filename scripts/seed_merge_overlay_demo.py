#!/usr/bin/env python3
"""Seed the PRM home with guaranteed duplicate pairs carrying private-overlay data — the manual
test bed for merge survivorship (prm#88): tags, notes, a photo, a custom field, groups, and
AI-gathered observations planted on BOTH sides of each pair, so merging in the workspace visibly
carries everything to the survivor. Synthetic data only; idempotent (re-running re-attaches).

    just demo                                        # seed the base ~1000-contact demo home first
    .venv/bin/python scripts/seed_merge_overlay_demo.py
    just serve                                       # then walk the checklist this script prints

Uses the same home resolution as `prm` (--data-dir/PRM_HOME/config/./prm-data via cli.config).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cli import ingest as ingest_mod  # noqa: E402
from cli.config import resolve_home  # noqa: E402
from core import apply, groups, media, relationships_db, schema, shared_db  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d494844520000000100000001080600000"
                    "01f15c4890000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")

# Two records per pair: same email (a CONFIDENT duplicate signal), different names (a conflict the
# merge UI makes you resolve). Search "mergetest" in the workspace to find them.
PAIRS = [
    ("Marge Mergetest", "Margaret Mergetest", "marge@mergetest.example"),
    ("Mel Mergetest", "Melvin Mergetest", "mel@mergetest.example"),
]


def _ingest_pair(home, name_a, name_b, email, tmp):
    for name, source in ((name_a, "apple_icloud"), (name_b, "google_takeout")):
        p = Path(tmp) / f"{name.replace(' ', '')}-{source}.vcf"
        p.write_text(f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{name}\r\nEMAIL:{email}\r\nEND:VCARD\r\n",
                     encoding="utf-8")
        ingest_mod.ingest([p], source=source, home=home, dry_run=False)


def _pair_ids(home, email):
    imap = relationships_db.identity_map(home.relationships_db)
    srids = [srid for _, e, _, srid in shared_db.search(home.shared_db, email.split("@")[0], limit=10)
             if e == email]
    cids = sorted({imap.get(s, s) for s in srids})
    if len(cids) != 2:
        raise SystemExit(f"expected 2 contacts for {email}, found {len(cids)} — "
                         "already merged? run `just clean-data && just demo` and re-run this script")
    return cids


def main() -> int:
    home = resolve_home(None)
    if not home.shared_db.exists():
        raise SystemExit("no shared.db — run `just demo` first")

    if schema.get_field(home.relationships_db, "how_we_met") is None:
        apply.define_field(home, label="How we met", kind="text")

    with tempfile.TemporaryDirectory() as tmp:
        for name_a, name_b, email in PAIRS:
            _ingest_pair(home, name_a, name_b, email, tmp)

    db = home.relationships_db
    for i, (name_a, name_b, email) in enumerate(PAIRS, 1):
        a, b = _pair_ids(home, email)
        # tags on both sides: 'shared' must union WITHOUT duplicating; 'work'/'family' must both arrive
        apply.set_field_value(home, a, "tags", "work")
        apply.set_field_value(home, a, "tags", "shared")
        apply.set_field_value(home, b, "tags", "family")
        apply.set_field_value(home, b, "tags", "shared")
        # notes on both sides: both must be KEPT (side by side) after the merge
        apply.set_field_value(home, a, "notes", f"note on side A of pair {i} — met at the conference")
        apply.set_field_value(home, b, "notes", f"note on side B of pair {i} — prefers email")
        # photo + custom field on ONE side only: must be adopted by the survivor whichever side wins
        apply.set_field_value(home, b, "photo", media.put(home, PNG, mime="image/png"))
        apply.set_field_value(home, b, "how_we_met", f"through Carol (pair {i})")
        # groups: one holding both halves (must collapse to one member), one holding a single half
        # (must follow that half to the survivor)
        for gname, members in ((f"Pair {i} — both halves", [a, b]), (f"Pair {i} — one half", [b]),):
            g = groups.find_group(db, gname) or apply.create_group(home, gname)
            apply.set_group_members(home, g["group_id"], add=members)
        # observations on one side: pending stays pending; rejected never resurfaces;
        # accepted returns to "pending your review" on the survivor
        pend = apply.observe_field(home, b, "url", f"https://pair{i}.mergetest.example",
                                   written_by="ai:seed", source="web")
        rej = apply.observe_field(home, b, "nickname", f"Pair{i}Nick", written_by="ai:seed", source="web")
        if relationships_db.get_observation(db, rej["obs_id"])["status"] == "observed":
            apply.reject_observation(home, rej["obs_id"])
        acc = apply.observe_field(home, b, "org", f"Acme {i}", written_by="ai:seed", source="github")
        if relationships_db.get_observation(db, acc["obs_id"])["status"] == "observed":
            apply.promote_observation(home, acc["obs_id"])
        print(f"pair {i}: {name_a!r} + {name_b!r} <{email}>  →  contacts {a[:8]}… / {b[:8]}…  "
              f"(pending obs {pend['obs_id'][:8]}…)")

    print(f"""
Seeded into {home.root}. Now `just serve` and search "mergetest" — the full checklist for what to
verify while merging each pair is in the PR description (prm#89) and tests/unit/test_merge_overlay.py.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
