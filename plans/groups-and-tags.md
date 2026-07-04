# PRM — Groups (and the tag browse surface)

*Status: approved plan (2026-07-04). Companion to [`../docs/prm-feature-spec.md`](../docs/prm-feature-spec.md)
(F2, INV-1/3/9) and [`../docs/roadmap.md`](../docs/roadmap.md) (v0.2). Builds on
[`v0.2-implementation-plan.md`](v0.2-implementation-plan.md), which deferred groups as a fast-follow —
this plan is that follow. Decisions below were confirmed with the user on 2026-07-04.*

## 1. Goal

Give the user **groups**: user-curated, named sets of contacts, as a private data layer — create any
number of groups, add any number of contacts to each, browse a group, edit its members, and *operate on*
a group (filter, bulk-add, export) instead of on all contacts or one contact. Also round out **tags**
with the one missing surface: a browse view (every tag, with description and contact count, click
through to the tagged contacts). Tag *management* already exists (the vocabulary modal) and is untouched.

**Why now (a deliberate roadmap acceleration).** Groups were deferred from the v0.2 relationship-store
work. Three things pull them forward:

- v0.3's delegated gathering is specified as "a daily check **over a chosen group**" — groups are the
  scoping primitive that work quietly assumes.
- PNT's **PR-1** private-schema contract mandates `groups` + `group_members` tables, and the canonical
  **`private-data-ops`** MCP contract is groups-centric (`list_groups` / `find_group` /
  `get_group_members`) — PRM is the second reference design and this is the missing demonstrator-parity
  piece ([`../../personal_network_toolkit/contracts/private-db.schema.sql`](https://github.com/richbodo/personal_network_toolkit/blob/main/contracts/private-db.schema.sql),
  [`mcp-private-data-ops.schema.json`](https://github.com/richbodo/personal_network_toolkit/blob/main/contracts/mcp-private-data-ops.schema.json)).
- The workspace sidebar has stubbed a Groups nav item since the v0.1 shell landed.

## 2. Decisions (confirmed 2026-07-04)

| Question | Decision |
| --- | --- |
| Data model | **Dedicated tables** (`groups` + `group_members`, PNT PR-1 shape) — *not* another builtin field on the `field_values` substrate. A group is an entity with its own name, note, and member set; the field substrate models labels *on* contacts, not sets *of* them. |
| Membership key | **Canonical `contact_id`** (the projection's entity), not raw `record_id` as in the PNT contract — re-pointed on merge so a group survives dedup. The `Architecture.md` attestation maps the deviation (same PK semantics, PRM's stable id). |
| MCP surface | **Read-only in this increment** — the three PNT-contract tools, consent-gated and access-logged like every private read. No group-write tool exists (the INV-3-style structural lock). AI-proposed membership is a later increment. |
| Group operations in scope | **Filter Contacts by group** · **bulk add from the contact list** · **export a group** (vCard). |
| Tags | **Add the browse view**; management stays in the existing modal. |

## 3. Data model — `relationships.db` schema v4

Two new tables in [`../core/schema/relationships.sql`](../core/schema/relationships.sql). The whole file
is idempotent (`IF NOT EXISTS` + `INSERT OR IGNORE`), so the v3→v4 migration is the existing
"run the script, bump `user_version`" path in `relationships_db._ensure_schema` — no bespoke migration.

```sql
CREATE TABLE IF NOT EXISTS groups (
    group_id        TEXT PRIMARY KEY,          -- opaque id (groups are renameable — not a name slug)
    name            TEXT NOT NULL,
    note            TEXT NOT NULL DEFAULT '',
    disclosure_tier TEXT NOT NULL DEFAULT 'private-sealed'
        CHECK (disclosure_tier IN ('private-sealed','private-shareable-on-consent')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL              -- drives list ordering (per the PNT contract)
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id   TEXT NOT NULL REFERENCES groups(group_id)     ON DELETE CASCADE,
    contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON DELETE CASCADE,
    added_at   TEXT NOT NULL,
    PRIMARY KEY (group_id, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_group_members_contact ON group_members(contact_id);
```

- **Disclosure is per-group**, defaulting to the most protective tier, changeable only in the workspace —
  the same model fields use (INV-10-adjacent; PR-7 data-floor). The External Access blast-radius math
  extends to count shareable groups.
- **Merge survivorship (the one subtle piece).** When `core/apply.py` runs a `merge` op it re-points the
  losing contacts' rows at the survivor. Group memberships must be re-pointed the same way, **in the same
  transaction and before** the losing `contacts` rows are removed (the FK cascade would otherwise
  silently drop them), with `INSERT OR IGNORE` semantics so a group containing both halves collapses to
  one row. **Pin this with a red test first** (repo rule: convert an absent guarantee into a red test).
- **Undo is free** — the snapshot ring covers all of `relationships.db`, so group CRUD and merge
  re-pointing are reversible by the existing snapshot-restore path.
- Tags need no schema work: the browse view reads the existing `tags` vocabulary
  (`field_definitions.config`) joined to `field_values` counts.

## 4. Core library — `core/groups.py`

A leaf over `relationships_db` (the `core/schema.py` discipline — no `cli` imports):

- `create(name, note) / rename / set_note / set_disclosure / delete`
- `add_members(group_id, contact_ids) / remove_members(group_id, contact_ids)`
- `list_groups()` — with member counts, most-recently-updated first
- `get_group(group_id)` — members hydrated via `core.projection` for display

All writes go through the daemon under the AC-PRM-C file-lock via the `core/apply.py` pattern —
**snapshot first, audit-log each operation** — so every group action is reversible and appears in the
audit trail, like contact edits do today.

## 5. Daemon API

- `GET  /api/groups` — list + counts; `POST /api/groups` — create.
- `GET  /api/groups/<id>` — detail + projected member rows; `POST /api/groups/<id>` — rename / note /
  disclosure / delete.
- `POST /api/groups/<id>/members` — `{add: […], remove: […]}` (covers single add from a contact *and*
  bulk add from the list).
- Contacts list/search gains `?group=<id>` — the reusable "operate on a group" scoping primitive.
- `GET  /api/tags` — the vocabulary with per-tag contact counts, for the browse view; click-through
  reuses the existing tag search.
- The workspace export endpoint gains a group scope (§7).

## 6. Workspace UI

- **Groups tab** — activate the stubbed nav item. List view: name, note, member count, updated; **New
  group**. Group view: member list with per-row remove, an **add-by-search** box, inline rename/note
  editing, **Export group**, delete (confirmed; reversible via Undo).
- **Contact detail** — an "Add to group…" control plus group chips (with ×-remove) on the card.
- **Contacts list** — a group filter, and a multi-select mode whose action bar offers "Add to group…"
  (the fast path to populating "emergency contacts").
- **Tags browse** — a compact surface beside Groups: every tag with description + count; clicking a tag
  filters Contacts by it. Management stays in the existing modal.

## 7. Group export

`prm export --group <name-or-id>` (CLI) + the workspace Export-group button: the existing vCard writer
over the projection filtered to the group's members. The export contains **contact data only** — group
name/membership stay local; it is an explicit user action, so the INV-1 posture is unchanged.

## 8. MCP surface — read-only, PNT parity

Extend `mcp_servers/private_data_ops.py` with `list_groups`, `find_group` (case-insensitive substring),
and `get_group_members`, matching the PNT contract shapes — including **orphan-tolerant nulls** when a
member no longer resolves after a re-mirror (AC-10). Gated exactly like existing private reads: nothing
in `pna` mode; only `private-shareable-on-consent` groups in `local-ai` / `cloud-exception` mode; every
read access-logged so it surfaces in External Access. **No group-write tool exists** — the same
structural enforcement as INV-3.

## 9. Docs & tests (same-change, per repo rules)

- **`docs/users-guide.md`** — capability-table rows + a Groups section + the tag-browse mention; status
  markers honest per slice (a capability is "✅ works" only in the PR that ships it).
- **`docs/roadmap.md`** — groups move from "deferred fast-follow" to in-progress/landed, linking here.
- **`mcp_servers/README.md`** — the three new tools (PR 3).
- **`docs/Architecture.md`** — PR-1 / private-data-ops parity rows, with the `contact_id` mapping note
  (PR 3, when the MCP surface makes the parity claim true).
- **Tests** — unit (CRUD, FK/cascade, counts, disclosure default), `test_apply` merge re-point
  (**red-first**), daemon API tests, MCP tool tests (contract shapes; sealed-by-default; `pna` mode
  returns nothing; access-log lines), export-scope test, and an e2e: create group → merge two members →
  membership survives → re-import preserves it.

## 10. Delivery — three PRs

1. **Store + core + daemon + Groups/Tags UI** — schema v4, `core/groups.py`, merge survivorship in
   `core/apply.py`, the daemon API, the Groups tab, add-from-contact, tags browse. Groups usable
   end-to-end.
2. **Group operations** — the Contacts group filter, bulk add from the list, group export (CLI +
   workspace).
3. **MCP read tools** — the PNT-parity surface + External Access integration + attestation rows.

Each PR: its own worktree branch off `main`, `pytest` green, users-guide updated in the same change.

## 11. Implementation notes / things to verify in code

- Confirm exactly how `apply.py`'s merge op disposes of losing `contacts` rows, and order the
  `group_members` re-point before it (the red test in §9 pins this).
- `seed_identities` creates a `contacts` row per source record 1:1, so the `group_members → contacts` FK
  is satisfiable for every projected contact — verify for contacts created *after* a group exists
  (re-import of new records).
- `get_group_members` orphan tolerance: a `contact_id` whose records vanished after a re-mirror should
  return nulls for display fields, not error (AC-10).
- The `?group=` filter must compose with the existing FTS search path (search *within* a group).
