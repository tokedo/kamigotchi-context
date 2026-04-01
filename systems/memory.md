# Agent Memory System

Persistent, account-specific state that makes the agent stateless between
sessions. A fresh agent reads this file to understand the schema, then reads
`memory/` to pick up where the last session left off.

The repo contains static game knowledge (committed, shared). `memory/` contains
one player's account-specific state (gitignored, never committed).

## Memory Types

| Type | File | Purpose |
|---|---|---|
| Account snapshot | `memory/account.md` | Who am I? Kami roster, wallet, room, key inventory. Perception cache |
| Plans | `memory/plans/*.md` | Hierarchical goals the agent is pursuing |
| Decision log | `memory/decisions.md` | Why key decisions were made — rationale archive for plan revision |

## Account Snapshot (`memory/account.md`)

Cached perception snapshot so the next session doesn't start blind. Updated at
end of every session. Contains:

- Account entity ID, owner address, operator address
- Current room
- Kami roster — for each Kami:
  - Entity ID, name, token index
  - Level, affinities (body/hand)
  - Current state (RESTING / HARVESTING / DEAD)
  - Approximate HP
  - Notable equipment
  - Skill build summary
- Key inventory: Musu, Onyx Shards, Gacha Tickets, notable items
- Active quests (indices, progress notes)
- Timestamp of last update

**This is a cache, not source of truth.** The agent should re-perceive on-chain
state each session and update this file. But it provides starting context so the
agent knows what to focus on before making any RPC calls.

### Template

```markdown
# Account Snapshot

Updated: <ISO timestamp>

## Identity
- Account entity ID: `<uint256>`
- Owner: `<address>`
- Operator: `<address>`
- Room: <index> (<name>)

## Kami Roster

| # | Name | Index | Level | Affinities | State | ~HP | Equipment | Skills |
|---|---|---|---|---|---|---|---|---|
| 1 | ... | ... | ... | EERIE/SCRAP | HARVESTING | ~45/80 | Wooden Shield | Guardian 15 |

## Key Inventory
- Musu: <amount>
- Onyx Shards: <amount>
- Gacha Tickets: <amount>
- Notable: <item>: <amount>, ...

## Active Quests
- Quest #<index> (<name>) — <progress notes>

## Notes
<anything the next session should know>
```

## Plan Hierarchy (`memory/plans/`)

Plans are markdown files with YAML frontmatter that form a tree.

### Plan Schema

```markdown
---
id: plan-<short-slug>
status: active | paused | completed | abandoned
type: strategic | tactical | routine
parent: plan-<parent-slug> | null
created: <ISO timestamp>
updated: <ISO timestamp>
---

# <Plan title>

## Goal
What we're trying to achieve and why.

## Success criteria
Concrete, measurable conditions that mean this plan is done.

## Current state
Where we are right now. Updated each session.

## Children
- [plan-<child-slug>](plan-<child-slug>.md) — status: active — brief description

## Next actions
What the agent should do next to advance this plan. Concrete steps.

## Notes
Anything relevant — risks, dependencies, observations.
```

### Plan Levels

| Level | Scope | Example | Lifetime |
|---|---|---|---|
| **Strategic** | Long-term goal | "Complete main quest line", "Build dominant harvester" | Weeks–months. 2–4 active per account |
| **Tactical** | Sub-goal with clear success criteria | "Level Kami #3 to 32", "Farm Pine Cones for recipe X" | Days–weeks. Children of strategic plans |
| **Routine** | Concrete session instructions | "Harvest Kami #3 at Fungal Hollow, collect every 30min, stop at 40% HP" | Hours. Children of tactical plans |

### Linking

- Plans reference their parent via `parent:` in frontmatter
- Plans list children in the `## Children` section
- This creates a navigable tree: strategic → tactical → routine

### Plan Index (`memory/plans/INDEX.md`)

Flat list of all plans with status, type, and one-line summary. The agent reads
this first to orient itself. Keep it concise.

```markdown
# Plan Index

## Active
- [plan-main-quest](plan-main-quest.md) — strategic — Complete main quest chain
  - [plan-reach-room-40](plan-reach-room-40.md) — tactical — Navigate to room 40 for quest #15
    - [plan-level-kami2-to-20](plan-level-kami2-to-20.md) — tactical — Level gate requires lvl 20
      - [plan-harvest-kami2-fungal](plan-harvest-kami2-fungal.md) — routine — Harvest at Fungal Hollow for XP
- [plan-musu-reserve](plan-musu-reserve.md) — strategic — Build 5000 Musu safety net

## Completed
- [plan-tutorial-quests](plan-tutorial-quests.md) — tactical — Completed 2026-03-28

## Abandoned
- [plan-scrap-node-farming](plan-scrap-node-farming.md) — tactical — Abandoned: Kami affinity mismatch made it inefficient
```

## Decision Log (`memory/decisions.md`)

Append-only log of **key decisions** and their rationale. Not every action —
only choices that future sessions might need to understand.

### Format

```markdown
## <ISO timestamp> — <Decision summary>

<Rationale: what was considered, why this choice was made.>

Related plan: plan-<slug>
```

### Example

```markdown
## 2026-04-01T14:30Z — Chose Guardian tree for Kami #2

Kami #2 (EERIE/SCRAP, Harmony 8) is our primary harvester. Guardian tree
reduces strain and improves liquidation defense. We need longer harvest
sessions more than we need combat power. Predator tree was considered but
we have no PvP strategic goal currently.

Related plan: plan-build-harvester-kami2
```

This log feeds plan revision sessions. When reviewing plans, the agent reads
recent decisions to check if the reasoning still holds.

## Plan Revision Triggers

Enter a plan revision session (update plans only, no game actions) when:

1. **Cold start** — `memory/plans/INDEX.md` doesn't exist or is empty. Create
   initial plans based on current account state
2. **Goal achieved** — a tactical/strategic plan's success criteria are met.
   Complete it, update parent, decide next steps
3. **Plan invalidation** — something broke the plan's assumptions (Kami
   liquidated, required item lost, quest has unmet prerequisites)
4. **Idle time** — all Kamis harvesting, no pending actions, cooldowns active.
   Good time to review and refine
5. **Periodic** — if `updated` on INDEX.md is older than ~6 hours of active
   play, do a review pass
6. **Human-triggered** — operator says "review plans" or similar

### During a plan revision session

1. Re-read account snapshot (update if stale)
2. Read decision log for recent entries
3. Walk plan tree top-down:
   - Are strategic goals still right?
   - Are tactical plans progressing?
   - Are routines still optimal?
4. Create new plans, update existing, abandon obsolete, mark completed
5. Update INDEX.md

## Session Lifecycle

Every agent session follows this flow:

```
1. READ  systems/memory.md           ← understand the schema (you're here)
2. READ  memory/account.md           ← who am I, what do I have
3. READ  memory/plans/INDEX.md       ← what am I working on
4. PERCEIVE on-chain state           ← RPC calls via systems/state-reading.md
5. UPDATE memory/account.md          ← reconcile cache with reality
6. CHECK plan revision triggers      ← if triggered, do revision session
7. EXECUTE plans                     ← follow active routines, advance tactical goals
8. LOG key decisions                 ← append to memory/decisions.md
9. UPDATE plan statuses, INDEX.md    ← reflect progress
```

If `memory/` is empty (cold start): skip steps 2–3, go straight to step 4
(perceive), then run a full plan revision to initialize.

## Initialization (Cold Start)

When `memory/` is empty or `memory/plans/INDEX.md` doesn't exist:

1. Create `memory/plans/` directory
2. Perceive full on-chain state (see [systems/state-reading.md](state-reading.md))
3. Write `memory/account.md` with current state
4. Assess account situation:
   - What Kamis do I have? What are their strengths?
   - What's my resource situation?
   - What quests are available?
   - What's my level and progression?
5. Create 2–4 strategic plans based on assessment
6. Break each into tactical sub-plans
7. Create routine plans for immediate session actions
8. Write `memory/plans/INDEX.md`
9. Begin execution
