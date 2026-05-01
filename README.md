# Kamigotchi Agent Context

A plug-and-play harness for AI agents that play Kamigotchi — a pure
on-chain MMORPG on Yominet. The repo bundles game-mechanics
documentation, calibrated catalogs, MCP tools that wrap on-chain
actions, and prebuilt operating modes for both supervised and
autonomous play.

> **Setting up?** → Start at [`SETUP.md`](SETUP.md). It walks through
> the two operating modes (Hybrid = interactive Claude Code, Fully
> Autonomous = VM with cron) and the steps to get the harness running.
>
> **Already set up?** → The agent reads [`CLAUDE.md`](CLAUDE.md) for
> operational instructions and [`executor/README.md`](executor/README.md)
> for the full MCP tool reference (64 tools).
>
> The rest of this README is the **agent's view of the game** — the
> mechanics, resources, and decision priorities the agent reasons over.

## Core Loop

```
HARVEST (earn Musu + XP) → COLLECT/STOP → REST (heal) → repeat
         ↓ side effects                      ↓ while resting
    scavenge rolls                      level up, equip, craft,
    liquidation risk                    trade, accept quests, move
```

All actions are on-chain transactions. Health syncs lazily on each action —
the Kami's actual HP is only computed when it does something.

## Key Resources

| Resource | How to get | What it's for |
|---|---|---|
| **Musu** (item 1) | Harvesting, trading, selling items | Base currency. Buy items, craft, trade fees, NPC shops |
| **XP** | Harvesting output (1:1), quest completion | Level up → skill points |
| **Skill Points** | 1 per level-up | Invest in skill trees (permanent bonuses) |
| **Onyx Shards** (item 100) | Scavenging, quests, drops | Revive dead Kamis (33 shards per revive) |
| **Stamina** | Account stat, regens over time | Movement between rooms, crafting |
| **Gacha Ticket** (item 10) | NPC shop, quests | Mint new Kamis |
| **Reroll Token** (item 11) | NPC shop, quests | Sacrifice a Kami for a new random one |

## Kami Stats

| Stat | Role |
|---|---|
| **Health** | Depletable. Drained by harvest strain, restored by resting. Death at 0 |
| **Power** | Scales harvest Fertility (base income rate) |
| **Violence** | Scales harvest Intensity (time-ramping bonus) + liquidation attack power |
| **Harmony** | Reduces harvest strain, speeds resting recovery, defends against liquidation |
| **Slots** | Equipment capacity (depletable) |

Effective stat: `Total = (1000 + boost) * (base + shift) / 1000`

## Kami Affinities

Each Kami has **body** and **hand** affinities from traits. Four types:
`EERIE`, `SCRAP`, `INSECT`, `NORMAL`.

- **Harvest**: matching Kami affinity to node affinity → up to 2x yield.
  Mismatch → 0.65x. See [systems/harvesting.md](systems/harvesting.md).
- **Combat**: rock-paper-scissors. EERIE > SCRAP > INSECT > EERIE.
  NORMAL is neutral.

## Systems

### Harvesting (primary income)
Assign Kami to a node → passively earn Musu. Drains HP via strain. Risk of
PvP liquidation. **This is where the agent spends most of its time.**
See [systems/harvesting.md](systems/harvesting.md).

### Health & Resting
While `RESTING`, HP regens at `~(Harmony + 20) * 0.6 / 3600` HP/s base.
A Harmony-10 Kami heals ~18 HP/hr. Full heal from 0 takes ~2.8h at Harmony 10.
If HP = 0, Kami dies. Revival costs 33 Onyx Shards and restores only 33 HP.
See [systems/health.md](systems/health.md).

### Leveling & Skills
XP cost per level: `40 * 1.259^(level-1)`. Each level grants 1 skill point.
Four skill trees: **Predator** (combat), **Enlightened** (sustain),
**Guardian** (defense), **Harvester** (harvest). Tier gates at 5/15/25/40/55/75/95
tree points. Mutual exclusions at tiers 3 and 6.
See [systems/leveling.md](systems/leveling.md).

### Scavenging (secondary loot)
Harvest output fills a per-node scavenge bar. When full, claim for a
droptable roll. Tier costs: 100–500 depending on node. Higher-cost nodes
have rarer droptables. Uses commit-reveal (two transactions).
See [systems/scavenging.md](systems/scavenging.md).

### Liquidation (PvP)
Another harvesting Kami on the same node can kill yours if your HP drops
below a threshold based on attacker Violence vs your Harmony. Victim dies,
loses most bounty. Attacker steals spoils and earns 1 Obol.
See [systems/liquidation.md](systems/liquidation.md).

### Crafting
Convert input items → output items via recipes. Costs stamina. Grants
account XP. Recipes may require specific room or level.
See [systems/crafting.md](systems/crafting.md).

### Trading (P2P)
Orderbook model: Create → Execute → Complete. One item each side, one side
must be Musu. Fees apply (creation fee + delivery fee; delivery waived in
room 66). Tax on Musu transfers.
See [systems/trading.md](systems/trading.md).

### NPC Shops
Buy/sell items at NPCs. Must be in same room (or NPC is global). Buy prices
may use GDA (dynamic pricing — rises with demand, decays over time).
See [systems/npc-shops.md](systems/npc-shops.md).

### Equipment
Equip items to Kami for stat bonuses. One item per slot. Must be `RESTING`
to equip/unequip. Default capacity: 1 slot.
See [systems/equipment.md](systems/equipment.md).

### Movement & Rooms
70 rooms across 4 z-planes. Move to adjacent rooms or via special exits.
Costs stamina. Gates may restrict access (level, quest flags, items).
Room 66 = Marketplace (no trade delivery fee). Room 1 = start.
See [systems/rooms.md](systems/rooms.md).

### Quests
~130 quests (main story chain, faction, side). Accept → complete objectives
→ claim rewards (items, reputation, flags). Most main quests are sequential.
Objectives track deltas from acceptance (snapshot-based).
See [systems/quests.md](systems/quests.md).

### Gacha & Sacrifice
Mint new Kamis with Gacha Tickets (commit-reveal randomness from pool).
Sacrifice permanently burns a Kami for a random item; pity system guarantees
uncommon every 20, rare every 100 sacrifices.
See [systems/gacha.md](systems/gacha.md).

### Day/Night Cycle
36-hour cycle: DAYLIGHT (0-11h), EVENFALL (12-23h), MOONSIDE (24-35h).
`phase = ((timestamp / 3600) % 36) / 12 + 1`. Some quests and mechanics
are phase-gated.
See [systems/day-night.md](systems/day-night.md).

### State Reading (perception)
How to query on-chain state, project HP/stamina between syncs, and
enumerate inventory/quests. The agent's "nervous system."
See [systems/state-reading.md](systems/state-reading.md).

### Memory (persistence)
Multi-account state — portfolio plans, per-account snapshots, decisions —
persisted in `memory/` (gitignored). A single mastermind agent controls 1–N
accounts. Reads the roster, perceives all accounts, then executes
portfolio-level plans that coordinate work across accounts.
See [systems/memory.md](systems/memory.md).

### Strategies (calibrated wisdom)
Proven decision heuristics learned through gameplay and human review. Committed
to the repo — shared across agent instances. Read `strategies/INDEX.md` before
planning. Insights flow from the decision log through the calibration loop:
agent plays, founder reviews, confirmed patterns get promoted to `strategies/`.
See [strategies/README.md](strategies/README.md).

### Factions & Reputation
Three factions: Agency, Elders (Mina), Nursery. Reputation gained via quest
rewards (2/4/6 per quest). Tracked as leaderboard scores.
See [systems/factions.md](systems/factions.md).

## Cooldowns

Base cooldown: **180 seconds** after most actions. Modified by
`STND_COOLDOWN_SHIFT` bonus (skills can reduce it). Always check cooldown
before planning the next action.
See [systems/accounts.md](systems/accounts.md).

## Prerequisites

**V1 agents use the [Kamibots API](integration/kamibots/)** for
world-state reads (projected HP, earnings, node occupancy) and strategy
execution (harvest loops, collect cycles). This is the primary
integration for V1 — see [integration/kamibots/](integration/kamibots/).

A local MUD sync that mirrors raw ECS state to PostgreSQL is available
for Phase 2 when we build our own perception layer. See
[integration/sync/](integration/sync/) (Phase 2).

## How to Execute Actions

All gameplay = transactions on **Yominet** (Chain ID `428962654539583`, flat `0.0025 gwei` gas).
RPC: `https://jsonrpc-yominet-1.anvil.asia-southeast.initia.xyz`

**Wallets**: two keys per player.
- **Owner** — registers account, trades, mints, approves ERC-20s. Holds ETH + tokens.
- **Operator** — all gameplay (harvest, move, equip, quests). Delegated from owner via `system.account.set.operator`.

**Calling a system**: hash the system ID string → resolve address from World → call `executeTyped(...)`.
```
address = World.systems().getEntitiesWithValue(keccak256(systemId))
```
Some systems use non-standard entry points (e.g., `reveal()`, `deposit()`, `batchTransfer()`)
instead of `executeTyped()`. Check [integration/system-ids.md](integration/system-ids.md)
for the full list and signatures.

**Entity IDs**: most are deterministic hashes — `keccak256(prefix, index)`. Accounts use
`uint256(ownerAddress)`. See [integration/entity-ids.md](integration/entity-ids.md).

Setup: [integration/bootstrap.md](integration/bootstrap.md) |
SDK patterns: [integration/sdk-setup.md](integration/sdk-setup.md) |
All system IDs: [integration/system-ids.md](integration/system-ids.md)

## Per-Tick Decision Checklist

On each agent decision cycle, evaluate in priority order:

1. **Death check**: if any Kami has HP = 0 and state = `DEAD`, decide whether
   to revive (costs 33 Onyx) or leave dead
2. **Harvest danger**: for each harvesting Kami, estimate current HP from
   strain. If HP < 30% of max, collect or stop immediately
3. **Cooldown gate**: if Kami is on cooldown, skip to next Kami or wait
4. **Collect vs stop**: if accrued bounty is substantial and HP is safe,
   collect (keeps harvesting). If HP is getting low or need to act, stop
5. **Scavenge claims**: if any node's scavenge bar has claimable tiers,
   claim them (then reveal droptable commits next tick)
6. **Droptable reveals**: if pending commit-reveal transactions exist,
   execute reveals
7. **Level up**: if any resting Kami has XP >= level cost, level up and
   spend skill point
8. **Quest progress**: check completable quests → complete → accept next
9. **Restart harvest**: if a Kami is resting and HP is healthy (>50% max),
   pick best available node and start harvesting
10. **Economy**: craft if profitable recipes available, trade if favorable
    orders exist, buy from NPC shops if needed

> When restarting harvest, node selection priority:
> affinity match > high-value droptable > low occupancy > low scav cost.
> See [systems/harvesting.md](systems/harvesting.md) for the full framework.

## Catalogs

| File | Contents |
|---|---|
| [catalogs/nodes.csv](catalogs/nodes.csv) | All harvest nodes: affinity, drops, level limits, scav cost |
| [catalogs/items.csv](catalogs/items.csv) | All items: type, tradability, stats |
| [catalogs/skills.csv](catalogs/skills.csv) | Skill trees: effects, costs, tiers, exclusions |
| [catalogs/recipes.csv](catalogs/recipes.csv) | Crafting recipes: inputs, outputs, stamina cost |
| [catalogs/rooms.csv](catalogs/rooms.csv) | Room map: coordinates, exits, gates |
| [catalogs/shop-listings.csv](catalogs/shop-listings.csv) | NPC shop items and prices |
| [catalogs/scavenge-droptables.csv](catalogs/scavenge-droptables.csv) | Node scavenge reward tables |

## Systems

| File | What it covers |
|---|---|
| [systems/harvesting.md](systems/harvesting.md) | Primary income loop: node selection, bounty, strain, liquidation risk |
| [systems/health.md](systems/health.md) | HP mechanics, resting recovery, death, revival |
| [systems/leveling.md](systems/leveling.md) | XP, level-up costs, skill trees, tier gates, build decisions |
| [systems/scavenging.md](systems/scavenging.md) | Scavenge bar, tier claiming, droptable commit-reveal |
| [systems/liquidation.md](systems/liquidation.md) | PvP kill mechanics, threat assessment, affinity combat triangle |
| [systems/crafting.md](systems/crafting.md) | Recipes, item types, using/burning/transferring items |
| [systems/trading.md](systems/trading.md) | P2P trades, Kami marketplace, fees, tax |
| [systems/npc-shops.md](systems/npc-shops.md) | NPC buy/sell, GDA pricing, newbie vendor, auctions |
| [systems/equipment.md](systems/equipment.md) | Equip/unequip, slot system, stat bonuses |
| [systems/rooms.md](systems/rooms.md) | World map, movement, stamina cost, gates |
| [systems/quests.md](systems/quests.md) | Quest types, objectives, rewards, community goals |
| [systems/gacha.md](systems/gacha.md) | Minting Kamis, rerolling, sacrifice, pity system |
| [systems/day-night.md](systems/day-night.md) | 36-hour phase cycle, phase-gated actions |
| [systems/factions.md](systems/factions.md) | Faction reputation, quest-based rep gains |
| [systems/accounts.md](systems/accounts.md) | Stats, stamina, cooldowns, owner/operator wallets |
| [systems/state-reading.md](systems/state-reading.md) | On-chain queries, HP/stamina projection, perception loop |
| [systems/memory.md](systems/memory.md) | Agent memory schema, plan hierarchy, session lifecycle |
| [strategies/README.md](strategies/README.md) | Calibrated decision heuristics from gameplay |
| [strategies/INDEX.md](strategies/INDEX.md) | Strategy index by topic (harvesting, builds, economy, coordination) |
