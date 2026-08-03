# Prime — prm
> Read-only orientation: understand the system, then summarize. Do NOT switch branches,
> pull, or create a worktree while priming — just orient. (CLAUDE.md § Conventions owns
> branching and worktrees.)

## Run
git ls-files
git status -sb          # branch + ahead/behind + dirty state
git worktree list       # sibling worktrees another agent may be using
just                    # the command surface
ls plans/               # see which plans exist before picking one

## Read
docs/prm-feature-spec.md    # what the product is; F-numbered features + INV- invariants
docs/roadmap.md             # version-by-version scope — tells you the CURRENT version
docs/Architecture.md        # how the pieces fit

**Then read the implementation plan for the current version, not v0.1.** `plans/` is named
by version (`v0.1-implementation-plan.md`, `v0.2-implementation-plan.md`) plus one file per
significant feature (`groups-and-tags.md`, `r11-append-only-tier.md`,
`ex-cloud-llm-workspace-handler.md`, …). The roadmap says which version is live; read that
version's plan, plus the feature plan for whatever you're working on. Feature plans carry a
status line — trust the code over a stale banner.

`docs/design-notes/` owns *why* a decision was made. Read the relevant note when a
constraint looks arbitrary — that's the reasoning you cannot reconstruct from code.

## Know before you touch code
- **`core/` is the invariant layer** (18 modules). The load-bearing ones:
  `relationships_db.py`, `disclosure.py`, `projection.py`, `apply.py`. Read those; grep the
  rest as needed rather than reading all ~4,000 lines.
- **`cli/` ingests, `daemon/` serves, `workspace/` is the browser UI, `mcp_servers/` is the
  AI surface.** The MCP servers are where the trust boundary lives.
- **INV-1: local-only.** Contact data does not leave the device. The single sanctioned
  exception is `EX-CLOUD-LLM`, and it is held by consent + honest signaling — an MCP server
  *cannot* detect which LLM consumes its output. Any new network call is a design change.
- **INV-2: the ingestor is the only writer of the raw Shared DB.**

## Before summarizing
- Note your branch, the current version per the roadmap, and which plan you read.
- Say which layer the task touches (core / cli / daemon / workspace / mcp) and whether it
  crosses the data-floor or the consent boundary.
