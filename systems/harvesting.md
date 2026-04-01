# Harvesting — Agent Decision Guide

Harvesting is the primary income loop. A Kami sits on a node, earns Musu over
time, takes HP strain, and can be liquidated (killed) by another player's Kami
on the same node.

GDD reference: `mechanics/economy/harvesting.md`, `mechanics/core-kami/health-healing.md`

## Lifecycle

```
START (kami + node) → accruing bounty, taking strain
  → COLLECT (take bounty, keep harvesting, reset cooldown)
  → STOP (take bounty, return to RESTING)
  → LIQUIDATED (killed by another player, lose most bounty)
```

Prerequisites for START: Kami is `RESTING`, off cooldown, HP > 0, account in
same room as node, node requirements met (e.g., level limit).

## Node Selection

Evaluate nodes in this priority:

### 1. Affinity Match (biggest multiplier)

Efficacy multiplier on Fertility (base income):

| Body + Hand match | Efficacy | Yield multiplier |
|---|---|---|
| Both match node | 1000 + 650 + 350 = **2000** | **2.0x** |
| Body matches, hand neutral | 1000 + 650 + 0 = **1650** | **1.65x** |
| Hand matches, body neutral | 1000 + 0 + 350 = **1350** | **1.35x** |
| Both neutral (NORMAL kami or node) | **1000** | **1.0x** |
| Body matches, hand mismatches | 1000 + 650 - 100 = **1550** | **1.55x** |
| Body mismatches, hand matches | 1000 - 250 + 350 = **1100** | **1.1x** |
| Both mismatch | 1000 - 250 - 100 = **650** | **0.65x** |

**Decision rule**: if body affinity matches → strong signal. If both match →
3x more income than full mismatch. Never harvest at a full-mismatch node
unless no alternative exists.

Affinity types: `EERIE`, `SCRAP`, `INSECT`, `NORMAL`.
- NORMAL Kami/node → always neutral (1.0x)
- Same non-NORMAL → Strong
- Different non-NORMAL → Weak

Dual-affinity nodes (e.g., "EERIE, SCRAP"): system picks best matchup order
for body (higher impact) vs hand.

### 2. Scavenge Droptable Value

Nodes with rarer scavenge drops are worth more long-term. Check
[catalogs/scavenge-droptables.csv](../catalogs/scavenge-droptables.csv) for
reward tables per node.

Higher scav cost (points to fill bar) = rarer drops:
- 100: starter nodes, common drops
- 200: mid-tier nodes
- 300: advanced nodes
- 500: premium nodes (Scrap Confluence, Techno Temple, Lotus Pool, etc.)

Scavenge points = harvest output. So higher Fertility = faster scavenge fills.

### 3. Node Yield Item

All nodes yield Musu (item index 1) as the primary harvest output. The
scavenge droptable determines secondary item drops. See
[catalogs/nodes.csv](../catalogs/nodes.csv) for the "Drops" column.

### 4. Level Restrictions

Some nodes have level caps (e.g., `Level Limit = 15` means only Kamis at or
below level 15). Check the node catalog before assigning.

### 5. Occupancy & Liquidation Risk

If other Kamis are harvesting on the same node, your Kami can be liquidated.
Prefer nodes with fewer active harvesters when your Kami is defensively weak
(low Harmony, high Violence attackers present).

## Bounty Accumulation

### Fertility (steady rate, Power-based)

```
Fertility = Power * 1500 * Efficacy / 3600
```

- Efficacy = affinity multiplier (see table above), default 1000
- Linear in Power: doubling Power doubles Fertility

### Intensity (ramping rate, Violence-based)

```
Intensity = 1e6 * (Violence * 5 + minutesElapsed) * 10 / (480 * 3600)
```

- Grows linearly with time (minutes since intensity reset)
- Small contribution early, significant over hours
- Resets on certain actions (equip changes)

### Total Bounty

```
Bounty = (Fertility + Intensity) * Duration * Boost / 1e9
```

- Duration = seconds since last sync
- Boost = 1000 base + skill/equipment bonuses

### Reference Output Rates

| Power | Efficacy | Approx Musu/hr (Fertility only) |
|---|---|---|
| 10 | 1000 (neutral) | ~15 |
| 10 | 2000 (perfect) | ~30 |
| 20 | 1000 (neutral) | ~30 |
| 20 | 2000 (perfect) | ~60 |

Intensity adds ~5-15% on top after the first hour, growing over time.

## Strain (HP Cost)

```
strain = ceil(harvestedAmount * 6500 * (1000 + strainBoost) / (1e6 * (Harmony + 20)))
```

Key insight: **strain scales with harvest output** — more Musu earned = more
HP lost. Harmony is the primary defense against strain.

### Strain-to-Bounty Ratio

For a Kami with Harmony H, base strain per Musu earned:

```
strain_per_musu ≈ 6.5 / (H + 20)
```

| Harmony | Strain per Musu | Musu before losing 50 HP |
|---|---|---|
| 5 | 0.26 | ~192 |
| 10 | 0.217 | ~231 |
| 15 | 0.186 | ~269 |
| 20 | 0.163 | ~308 |
| 30 | 0.13 | ~385 |

> Higher Harmony = longer harvest sessions before HP danger.

## When to Collect vs Stop

### HP Danger Zones

Monitor estimated HP and act:

| Current HP (% of max) | Action |
|---|---|
| > 50% | Safe to continue. Collect if bounty is large enough to justify cooldown |
| 30-50% | Collect now to bank bounty. Consider stopping if Harmony is low |
| 15-30% | **Stop immediately**. HP is in liquidation danger zone |
| < 15% | **Emergency stop**. Risk of strain-death or liquidation is critical |

### Collect Decision

Collecting triggers:
- Bounty transferred to account (split by tax if taxer set)
- XP = amount collected (feeds leveling)
- Scavenge bar incremented by harvest amount
- Cooldown resets (180s base)
- Harvest continues

**Collect when**: bounty is meaningful AND HP > 50% AND cooldown is clear.

### Stop Decision

Stopping does everything Collect does, plus ends the harvest → Kami goes to
`RESTING` and begins healing.

**Stop when**: HP is getting low, or you need the Kami to level up / equip /
move rooms / any non-harvest action.

## Liquidation Risk

Another player's Kami can kill yours if:
1. Both Kamis are `HARVESTING` on the **same node**
2. Your HP has dropped below the kill threshold

### Kill Threshold

```
threshold = animosity(attacker.Violence, victim.Harmony) * efficacy * victim.maxHP
```

- Animosity uses a Gaussian CDF over ln(Violence/Harmony) — higher attacker
  Violence relative to your Harmony = higher threshold
- Affinity matchups modify efficacy (attacker hand vs victim body)

**Practical rule**: if your Kami has low Harmony and has been harvesting a long
time (HP drained), any Violence-heavy Kami on the same node can potentially
liquidate you.

### Consequences of Liquidation

- **Your Kami dies** (state = `DEAD`, HP = 0)
- **Salvage**: you retain a small portion of bounty (scales with your Power)
- **Spoils**: attacker steals a portion (scales with attacker Power)
- **Remaining bounty is destroyed** (not transferred to anyone)
- **Revival costs 33 Onyx Shards** and only restores 33 HP

### Defensive Heuristics

- If Harmony is low (< 10), harvest in shorter sessions — collect early, stop
  before HP drops below 40%
- Avoid high-traffic nodes if your Kami can't sustain the fight
- High Harmony + low Violence = hard to liquidate (high effective threshold
  from defender side, low animosity from attacker perspective)
- Skills in **Guardian** tree increase defense threshold and salvage ratio
- Skills in **Enlightened** tree reduce strain (harvest longer safely)

> HEURISTIC: without occupancy data, assume any non-starter node may have
> active harvesters. Starter nodes (level limit 15) are safer for weak Kamis.

## Tax System

When starting a harvest, optionally set a taxer (e.g., guild leader). The
taxer receives a percentage of all collected bounty. If no tax needed, set
`taxAmt = 0`.

## Side Effects on Collection

Every collect/stop also triggers:
1. **XP** = Musu collected (1:1)
2. **Scavenge** = bar increment by harvest amount → claim when tier is full
3. **Score** = account leaderboard increment

## Quick Reference: Optimal Harvest Session

For a Kami with Power P, Harmony H, max HP = Total:

```
Safe harvest duration ≈ (Total * 0.5) / (strain_rate)
where strain_rate ≈ P * 1500 * Efficacy * 6500 / (3600 * 1e6 * (H + 20))
```

Simplified (neutral affinity, no bonuses):
```
safe_hours ≈ Total * (H + 20) / (P * 2708)
```

Example: Power=10, Harmony=10, HP=50:
```
safe_hours ≈ 50 * 30 / (10 * 2708) ≈ 0.55 hours ≈ 33 minutes to 50% HP
```

This Kami should collect every ~30 min and stop within ~1 hour.

## Node Catalog Reference

See [catalogs/nodes.csv](../catalogs/nodes.csv) for all 65 nodes with:
- Affinity type (for matching)
- Level limits
- Scavenge cost
- Drop descriptions

## How to Execute

All harvest calls use the **Operator** wallet. Gas is default except liquidate.

### System IDs

| Action | System ID |
|---|---|
| Start | `system.harvest.start` |
| Stop | `system.harvest.stop` |
| Collect | `system.harvest.collect` |
| Liquidate | `system.harvest.liquidate` |

### Harvest Entity ID

Derived deterministically from the Kami entity ID — no on-chain lookup needed:
```
harvestId = keccak256(abi.encodePacked("harvest", kamiEntityId))
```
One harvest per Kami at a time. Use `harvestId` for stop/collect/liquidate calls.

### Function Signatures

**start** — `executeTyped(uint256 kamiID, uint32 nodeIndex, uint256 taxerID, uint256 taxAmt)`
Pass `0, 0` for taxerID/taxAmt (player-initiated). Batch variant:
`executeBatched(uint256[] kamiIDs, uint32 nodeIndex, uint256 taxerID, uint256 taxAmt)`

**stop** — `executeTyped(uint256 harvestId)`
Auto-collects bounty. Batch: `executeBatched(uint256[] ids)`.
Allow-failure variant: `executeBatchedAllowFailure(uint256[] ids)` — skips invalid harvests.

**collect** — `executeTyped(uint256 harvestId)`
Partial collection, harvest continues. Batch: `executeBatched(uint256[] ids)`.
Allow-failure variant: `executeBatchedAllowFailure(uint256[] ids)`.

**liquidate** — `executeTyped(uint256 victimHarvID, uint256 killerID)`
**Gas limit: 7,500,000 required.** Both Kamis must be harvesting on the same node.

### Gas Notes

- Start/stop/collect: default gas limit is fine
- Liquidate: hardcode `gasLimit: 7_500_000` — complex PvP logic
- Gas price is flat `0.0025 gwei`, cost is negligible

Full details: [integration/api/harvesting.md](../integration/api/harvesting.md)
