# Kamibots API Integration

> **PLACEHOLDER** — Endpoint details, auth mechanism, and full spec
> pending from Kamibots team (Coopes). Will be updated when `agents.md`
> is shared. Do not build against assumed endpoints.

## What Kamibots Provides

The Kamibots API gives agents two capabilities:

### Strategy execution (write)

Agent sets up repeated strategies via API instead of managing individual
transactions. Kamibots handles the repetitive execution loop.

Example: "start harvest loop for Kami #3 on node 14, collect at 40% HP,
restart when HP recovers above 50%." The agent defines the strategy;
Kamibots runs it.

- Strategies cover: harvest loops, collect/stop cycles, feeding, rest timers
- Agent launches, monitors, and stops strategies via API calls
- Cost model: likely covered by harvest tax (same as current Kamibots
  user model) — details TBD

### World state reads (read)

Pre-computed game-meaningful state — no local interpretation needed.

- Projected HP (current, not last-synced)
- Earnings and bounty accrual
- Node occupancy
- Account summaries
- Strategy status and history

This is the **v1 shortcut** while the self-contained interpretation
layer (local MUD sync → game logic → game-meaningful state) is being
built. See [integration/sync/](../sync/) for the raw sync path.

## Auth

Agent-specific authentication via API keys. Details TBD from Coopes'
`agents.md` doc.

## v1 vs Long-Term Architecture

```
v1 (now):     Agent ──► Kamibots API ──► game state + strategy execution
Long-term:    Agent ──► local MUD sync + interpretation layer ──► game state
              Agent ──► direct contract calls ──► strategy execution
```

Kamibots API is a **v1 convenience**, not a permanent dependency. The
long-term architecture is fully self-contained: the agent reads raw ECS
state from the local MUD sync, interprets it using game logic (formulas
in `systems/` files), and executes transactions directly against the
World contract.

Use Kamibots API for:
- Pre-computed state reads (saves building the interpretation layer)
- Strategy execution (saves building the harvest loop manager)

Use local MUD sync for:
- Aggregate queries Kamibots doesn't cover (full world scans)
- Building toward self-contained operation
