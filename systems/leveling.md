# Leveling & Skills — Agent Decision Guide

When to level up, how skill points work, which tree to invest in.

## XP Sources

Kami XP comes from:
- **Harvesting** — XP = Musu collected (1:1), on collect or stop
- **Kill salvage** — victim Kami gets XP = salvage amount
- **Item effects** — some items grant XP when used on a Kami

> Account XP (from movement, crafting) is a **separate pool** and does NOT
> feed Kami leveling.

## Level-Up Cost

XP cost to advance from current level:

```
cost = floor(40 * 1.259^(level - 1))
```

XP is **consumed** on level-up — surplus is retained.

| Level | XP to next | Cumulative |
|---|---|---|
| 1 | 40 | 40 |
| 2 | 50 | 90 |
| 3 | 63 | 153 |
| 4 | 80 | 233 |
| 5 | 100 | 333 |
| 6 | 126 | 459 |
| 7 | 159 | 618 |
| 8 | 200 | 818 |
| 9 | 252 | 1,070 |
| 10 | 317 | 1,387 |
| 15 | 1,007 | 5,530 |
| 20 | 3,198 | 17,330 |
| 25 | 10,162 | 53,000 (approx) |
| 30 | 32,285 | 163,000 (approx) |

### Decision: When to Level Up

Level up when:
- Kami is `RESTING` (required)
- `currentXP >= levelCost`
- You have a skill point target in mind (don't waste SP on nothing)
- **Batch levels**: if XP covers multiple levels, call `level()` repeatedly
  (one level per call, no batch function)

Don't rush to level up if:
- The Kami is in the middle of a productive harvest session (stop first)
- You're near a level cap on a node — leveling past a node's level limit
  locks you out

## Skill Points

Each level-up grants **1 skill point**. New Kamis start with 1 SP at level 1.

All skills currently cost **1 SP per upgrade level**.

### Respec

Costs 1 **Respec Potion** (item 11403). Refunds all skill points for that
Kami. Full reset — all skills removed, all bonuses cleared.

## Skill Trees

4 trees, each with **6 tiers** of 3 skills = 72 total skills.

Config defines 8 tier slots (0–7), but only tiers 1–6 have deployed skills.
Tier 0 is unlocked at 0 points (no skills there), tier 7 (95 points) has no
skills currently. The agent only needs to plan around tiers 1–6.

| Tree | Focus | Best for |
|---|---|---|
| **Predator** | Violence, attack threshold, spoils, cooldown | Liquidation-focused Kamis |
| **Enlightened** | Resting recovery, harvest bounty, strain reduction | Sustain harvesting |
| **Guardian** | Harmony, defense threshold, salvage, health | Tanky harvesters |
| **Harvester** | Power, harvest fertility/bounty, strain reduction | Max income harvesters |

### Tier Gates

Must invest N total tree points before skills at that tier unlock:

| Tier | Tree Points Required | Skills |
|---|---|---|
| 1 | 5 | 3 per tree |
| 2 | 15 | 3 per tree |
| 3 | 25 | 3 per tree (mutually exclusive — pick 1) |
| 4 | 40 | 3 per tree |
| 5 | 55 | 3 per tree |
| 6 | 75 | 3 per tree (mutually exclusive — pick 1) |

Tree points = total SP spent in that tree (each skill costs 1, so
tree points = number of skill upgrades in tree).

### Tier 3 and Tier 6 Exclusions

At tiers 3 and 6, the three skills are **mutually exclusive** — choosing one
locks out the other two in that tier. Choose carefully; only respec can undo.

## Skill Effects

Skills grant bonuses via these effect types:

| Key | Effect | Used by |
|---|---|---|
| `SHS` | +Health (shift) | Guardian |
| `SPS` | +Power (shift) | Harvester |
| `SVS` | +Violence (shift) | Predator |
| `SYS` | +Harmony (shift) | Guardian |
| `HFB` | Harvest Fertility boost (%) | Harvester |
| `HIB` | Harvest Intensity boost (Musu/hr) | Guardian |
| `HBB` | Harvest Bounty boost (%) | Enlightened, Harvester |
| `ATS` | Attack threshold shift (%) | Predator |
| `ATR` | Attack threshold ratio (%) | Predator |
| `ASR` | Attack spoils ratio (%) | Predator |
| `DTS` | Defense threshold shift (%) | Guardian |
| `DTR` | Defense threshold ratio (%) | Guardian, Harvester |
| `DSR` | Defense salvage ratio (%) | Guardian |
| `RMB` | Resting recovery boost (%) | Enlightened |
| `SB` | Strain boost (%) | Enlightened, Harvester (negative = less strain) |
| `CS` | Cooldown shift (seconds) | Predator (negative = shorter cooldown) |

Percent effects have precision 3 (×1000 in storage).

## Skill Build Decisions

### Primary Harvester

Goal: maximize income, minimize downtime.

- **Harvester tree** for Power + Fertility bonuses
- **Enlightened tree** for strain reduction + recovery boost
- At tier 3/6, choose sustain over combat options

### PvP Liquidator

Goal: kill other players' Kamis for spoils.

- **Predator tree** for Violence + attack threshold
- Some **Guardian** for survivability
- At tier 3, choose spoils-boosting option

### Defensive Tank

Goal: harvest safely on contested nodes.

- **Guardian tree** for Harmony + defense threshold + health
- **Enlightened tree** for strain reduction
- High Harmony makes the Kami very hard to liquidate

### Planning Tip

- Calculate total SP needed to reach the next meaningful tier gate
- Set a tactical plan: "Level Kami to X to unlock tier Y in Z tree"
- Check [catalogs/skills.csv](../catalogs/skills.csv) for exact skill effects

## How to Execute

**Level up** — `system.kami.level` (Operator wallet)
```
executeTyped(uint256 kamiID)
```
- Kami must be `RESTING`
- Must have `XP >= levelCost`
- Grants 1 skill point

**Upgrade skill** — `system.skill.upgrade` (Operator wallet)
```
executeTyped(uint256 holderID, uint32 skillIndex)
```
- `holderID` = Kami entity ID (for Kami skills)
- Kami must be `RESTING`
- Must meet tier gate requirement
- Must not violate exclusions

**Respec** — `system.skill.respec` (Operator wallet)
```
executeTyped(uint256 targetID)
```
- Consumes 1 Respec Potion (item 11403)
- Refunds all SP, clears all skill bonuses

## Cross-References

- Skill catalog: [catalogs/skills.csv](../catalogs/skills.csv)
- XP from harvesting: [harvesting.md](harvesting.md)
- Stat formulas (how boosts apply): [accounts.md](accounts.md)
