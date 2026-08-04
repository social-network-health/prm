# CLAUDE.md

Personal Relationship Manager (PRM) — a **local-only** Personal Network Application (PNA): it mirrors
a person's contacts from everywhere they're scattered (Google, Apple, LinkedIn, Facebook, loose
`.vcf`/`.csv`) into one local store they own, lets them keep private relationship data on top, and
lets an AI read and help maintain that data on their behalf. **Contact data never leaves the device.**
PRM is a **reference design** for the [Personal Network Toolkit](https://github.com/social-network-health/personal_network_toolkit)
(PNT, the sibling spec repo); this is an **application**, not a spec.

**Read in this order:** [`README.md`](README.md) →
[`docs/users-guide.md`](docs/users-guide.md) (install + how-to; the user-facing source of truth) →
[`docs/prm-feature-spec.md`](docs/prm-feature-spec.md) (what the product is) →
[`docs/roadmap.md`](docs/roadmap.md) (version-by-version scope) →
[`plans/v0.1-implementation-plan.md`](plans/v0.1-implementation-plan.md) (how v0.1 is built).
Install with `pip install -e ".[dev]"` and run `pytest` before pushing.

<!-- BEGIN SHARED: org-conventions v7 -->
<!-- Canonical copy: social-network-health/docs/shared/org-conventions.md
     Do not edit this block in place. Edit the canonical copy and propagate. -->

> **⚙ Shared, generated section — don't edit it here.** Everything from this line down to
> *"Changing this block"* is identical in every repo in the org. Change it in the canonical
> copy (hub `docs/shared/org-conventions.md`) and run `just sync-conventions`; an edit made
> in place will be reported as `EDITED` and then overwritten. Repo-specific guidance belongs
> in this file's *other* sections, which the tooling never touches.

## The organization

The repos of the **[social-network-health](https://github.com/social-network-health)** GitHub
org. A developer normally has them **all checked out side by side in one parent directory**,
so from any repo root every other repo is at `../<name>`. Write cross-repo paths relative to
the repo root, never absolute — the parent directory differs per host.

The set changes as repos are added and archived, so no document states a count; ask the org
(`gh repo list social-network-health`) or read `RELATED_REPOS.md`.

**[`RELATED_REPOS.md`](https://github.com/social-network-health/social-network-health/blob/main/RELATED_REPOS.md)**
in the hub repo is the single source of truth for what those repos are and what each is for.
Don't restate the list in a repo's own docs — a second copy is a second thing to forget.

The layout is a convention of the working environment; it could change, but it holds for now.
It lives in `CLAUDE.md` rather than agent memory because **memory is keyed to the working
directory** — a worktree at a different path starts with a fresh memory dir. A committed file
is the only channel that reaches every worktree and every concurrent agent.

## Planning has four layers

| # | Question | Lives in |
|---|---|---|
| 1 | "What is the software program?" | hub [`software-plan.md`](https://github.com/social-network-health/social-network-health/blob/main/software-plan.md) — the M1/M2/M3 summary |
| 2 | "What should the org be doing?" | hub [`plans/`](https://github.com/social-network-health/social-network-health/tree/main/plans) + `plans/ORG-TASKS.md` |
| 3 | "Where is this repo headed?" | **this repo's** `docs/roadmap.md` |
| 4 | "What's in flight?" | **this repo's** GitHub issues and active branches |

Record a thought at the layer matching its scope.

**Layer 2 is org-only.** Work actionable inside one existing repo belongs in that repo;
`ORG-TASKS.md` links down to it rather than restating its status. **Layer 1 is narrower than
the organization** — `software-plan.md` summarizes the software and research program, not community
building, the toolkit wiki, or educational materials.

Dated files under `plans/` are append-only thinking artifacts. Never update one; write a new
one. `ORG-TASKS.md` is the sole exception — it is kept current.

## Cross-repo working rules

Each of these was learned the hard way in one repo. They apply in all of them.

- **PR and issue bodies via `--body-file`, never an inline `--body`.** Backticks and `$(…)`
  get shell-interpreted and silently drop content — a commit hash has been lost this way.
- **After a PR merges, verify every intended commit actually landed.** A dropped commit is
  silent; recover it in a follow-up rather than assuming the merge was faithful.
- **Triage every test failure as pre-existing or newly-introduced before shipping.** Stash
  and re-run against the base to tell which. Never absorb a pre-existing red into unrelated
  work, and never claim green while a known red stands.
- **Upstream `main` beats local staging plans.** In a multi-agent setup another agent may
  have already filed, merged, or evolved a cross-repo contribution. Check the upstream repo's
  `main` before developing one further — local `plans/` lag.
- **Fail loudly.** Convert an absent guarantee into a red test or a lint failure, never a
  silent pass. Deferrals carry an honest status marker — a strict-xfail, an `Open`/`partial`
  attestation, a documented "⏳ next" — never a bare `TODO` claiming a property the code
  doesn't deliver.
- **One source of truth per fact.** Restating a fact in a second document creates a drift
  surface. Put it in the doc that owns the category and link from the others.
- **Orient without moving; branch only to work.** Reading and priming never need a branch
  change — in a multi-worktree setup `main` is often checked out elsewhere, so a checkout
  fails or strands uncommitted work. Run `git worktree list` before starting. Repo-specific
  worktree setup and port serialization live in that repo's own sections.
- **A sync rule without a mechanical check is a wish.** Anything that must hold in more than
  one repo ships with a command that verifies it, and the rule names the command. Nobody
  eyeballs every repo by hand, so silent drift is the default outcome otherwise.
- **Add a load-bearing document or module → update `.claude/commands/prime.md` in the same
  PR.** Priming is how every agent gets its systems-level picture of a repo, and a prime that
  misses the file where the invariants live sends every future session searching for it. This
  is the same rule as "a user-visible change updates the users guide in the same PR", applied
  to the agent's entry point. Prime is bespoke per repo, so no checksum catches this one —
  the PR is the only gate.
- **Prime is expensive; not priming is more expensive.** `CLAUDE.md` loads every session, so
  it holds what is always true and stays short. Prime is opt-in and costs tokens, so it holds
  the *reading list* — which files give systems-level understanding, and which to skim rather
  than read. Keep prime curated: name the seams, never glob a directory.
- **Brainstorms are private and live in `snh-private`, never in a public repo.** Use the
  **`snhb`** skill: it captures to `../snh-private/brainstorms/<this repo>/`, checkpoints
  after every answer, and commits at session end so the thinking follows you between
  machines. It also *searches* every repo's brainstorms — ask it what you previously decided
  about something rather than re-deriving it. They're private because unreviewed thinking
  wastes the reader's time, not because it's secret; when one is worth publishing, review it
  and put a **cleaned copy** in the public destination, leaving the original where it is.

## Changing this block

This block is generated. To change it: edit the canonical copy, bump the version in both
markers, run `just sync-conventions` from the hub repo, then open one PR per repo.
`just check-conventions` verifies every copy matches; `just check-org` runs every org check.
Full procedure: hub `docs/org-upkeep.md`.

<!-- END SHARED: org-conventions v7 -->

## Upstream and the other reference design

- `../personal_network_toolkit` — the PNA Toolkit (PNT): the universal spec, contracts, and
  lints this design attests conformance to. Its `origin/main` is the source of truth for
  upstream work.
- `../fellows_local_db` — the first reference design (Directory Archive), for cross-design
  comparison.

A change here can have cross-repo implications for PNT (a conformance or contract change);
when in doubt, read PNT's `spec/`.

## Keep the docs current

[`docs/users-guide.md`](docs/users-guide.md) is the user-facing source of truth, and it carefully
marks **what works today vs. what's coming**. Any change that alters a behavior a user would notice —
a new parser/source, a CLI flag, what `--dry-run` does, the demo flow, or moving a capability from
"⏳ next" to "✅ works" — **MUST update `docs/users-guide.md` (and its capability table) in the same
change.** The status markers are a promise to the reader; keep them honest. This rule exists because
docs like these drift behind the code the moment a change skips them.

## Documentation map — one source of truth per fact

Restating a fact in a second doc creates a drift surface. Each doc *owns* a category and the others
*link* to it rather than re-explaining:

- **`docs/prm-feature-spec.md`** — what the product is and which PNT use case / contracts it realizes.
  Owns *the product definition*.
- **`docs/roadmap.md`** — version-by-version scope and what's deferred. Owns *what's coming, and when*.
- **`plans/v0.1-implementation-plan.md`** — how the current version is built (architecture, invariants,
  module seams). Owns *implementation detail*.
- **`docs/design-notes/`** — design *rationale*: why a decision was made, the constraint that forced it,
  alternatives rejected (e.g. the LLM/MCP trust boundary and `EX-CLOUD-LLM`). Owns *the reasoning behind
  decisions* — distinct from the roadmap, which owns *what's coming*.
- **`docs/users-guide.md`** — task-ordered how-to for users, plus the "what works today" status table.
  Owns *what a user does, step by step*. Links to the spec / roadmap for definitions; does not restate them.
- **`docs/reference/`** — third-party *source* format references (not PRM's own schemas), and
  `source_validation_status.md`. Owns *external format facts*.
- **`README.md`** — one-paragraph orientation + the doc index. Links out; owns nothing else.

When you add a fact, put it in the doc that owns its category and link from the others.

## Conventions

- **Python 3.10+.** Runtime deps are kept tiny and deliberate — today just `vobjectx` (the vCard lexer;
  the older `vobject` is an accepted drop-in fallback). Don't add a runtime dependency without a reason
  recorded in `pyproject.toml` and the implementation plan. `pytest` is dev-only (`.[dev]`).
- **Local-only is the core invariant — INV-1.** In **PNA mode**, contact and user-authored data stay on
  the device; PRM is *Never-SaaS* (any server is a delivery channel, not a service). The one sanctioned
  way data leaves the device is the named **`EX-CLOUD-LLM`** exception — connecting a cloud MCP client
  like Claude Desktop — and only when handled to PNT's exception contract: explicit consent *before* the
  raise, a persistent "not a PNA right now" signal while active, and a reversible return-to-PNA-mode path
  (mode only — it cannot recall data already sent). See PNT
  [`spec/exceptions.md`](https://github.com/social-network-health/personal_network_toolkit/blob/main/spec/exceptions.md)
  (`EX-CLOUD-LLM`, handler clauses EX-H1–H8). **An MCP server cannot detect or restrict which LLM consumes
  its output** — `clientInfo` is self-reported and app-level, and MCP's OAuth runs client→server — so the
  boundary is held by consent + honest signaling, *never* by trying to identify the client. Any *other*
  off-box path (telemetry, cloud sync, a new network call) is a design change to flag explicitly, not a feature.
- **The ingestor is the only writer of the raw Shared DB (INV-2).** Read/search paths read it; they don't
  mutate it.
- **Tests pin behavior** — run `pytest` after changes; put manual test/QA steps in the **PR description**.
- **Default posture: orient without moving; branch only to work.** Reading or priming never needs a
  branch change — don't `git checkout main` / `git pull` just to get oriented (in a multi-worktree
  setup `main` is often checked out elsewhere, so the checkout fails or strands uncommitted work).
  Create a worktree (next bullet) when you start *actual work*, and run `git worktree list` first to
  spot a sibling already on a related branch.
- **Multiple agents on one host → one git worktree each.** Give every concurrent Claude Code / agent its
  own worktree so a `git checkout` in one can't yank the branch (or uncommitted work) out from under
  another: `git worktree add ../prm-wt-<branch> -b <branch>`, then `just setup` in it (fresh `.venv`), or
  symlink `.venv` / `prm-data/` in to share them. Worktrees isolate the filesystem, **not** the workspace
  port **8770** — edits and non-server tests run in parallel, but `just serve` and any server-based run
  must be **serialized** across worktrees (`just doctor` flags 8770 in use; `just port` *frees* it, which
  kills whatever holds it — including a sibling's server — so coordinate). If you share `prm-data/`,
  don't `just clean-data` / re-ingest while a sibling is serving. `git worktree remove ../prm-wt-<branch>`
  when done.

## Fail loudly — no silent gaps

- **Convert an absent guarantee into a red test, never a silent pass.** A parser that can't yet handle a
  field should have a test that pins the current behavior, not a quiet skip that reads as "handled."
- **Deferrals are honest** — an explicit status marker (the users-guide "⏳ next", a roadmap "deferred"
  note, a documented `--dry-run`), never a bare `TODO` that *claims* a capability the code doesn't deliver.
- **Validate sources against real exports.** [`docs/reference/source_validation_status.md`](docs/reference/source_validation_status.md)
  tracks which export formats were validated against a real-world export versus built from documentation
  alone. When you add or change a parser, update that status — don't let a doc-only fixture masquerade as
  validated.
