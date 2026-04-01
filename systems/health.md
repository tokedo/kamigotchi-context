# Health & Death — Agent Decision Guide

How HP works, when to heal, when to revive.

## HP Mechanics

HP is a **depletable stat** tracked in the `sync` field. It decreases from
harvest strain and increases from resting. HP is **lazy-synced** — only
updates on-chain when the Kami performs an action.

Between actions, the agent must **project** current HP locally.
See [state-reading.md](state-reading.md) for projection formulas.

### Effective (Max) HP

```
maxHP = max(0, floor((1000 + boost) * (base + shift) / 1000))
```

A freshly created Kami has ~50 base HP (varies by traits).

## Resting Recovery

While `RESTING`, HP regenerates passively:

```
metabolism = 1000 * (Harmony + 20) * 600 * (1000 + restBoost) / 3600
recovery = floor(elapsedSeconds * metabolism / 1e9)
```

Where `restBoost` = `REST_METABOLISM_BOOST` bonus (from skills/equipment,
default 0).

Simplified (no bonuses):
```
healRate ≈ (Harmony + 20) * 0.6 / 3600   HP/sec
```

| Harmony | HP/hour | Time to heal 50 HP |
|---|---|---|
| 5 | 15.0 | 3.3 h |
| 10 | 18.0 | 2.8 h |
| 15 | 21.0 | 2.4 h |
| 20 | 24.0 | 2.1 h |
| 30 | 30.0 | 1.7 h |

HP is capped at maxHP.

### When to Wait for Healing

- If HP > 50% of max → safe to start harvesting
- If HP 30–50% → can harvest short sessions, but risky on contested nodes
- If HP < 30% → **wait for more healing** before harvest
- Factor in how long the Kami will harvest and the projected strain

## Death

A Kami dies when HP reaches 0. Causes:
- **Harvest strain** — HP drained to 0 while harvesting
- **Liquidation** — killed by another player (see [liquidation.md](liquidation.md))
- **Sacrifice** — voluntary permanent death (see [gacha.md](gacha.md))

### Dead State

State = `DEAD`, HP = 0. Cannot:
- Harvest, level up, equip/unequip, use items, accept quests, move, trade

### Decision: Revive or Leave Dead?

Revive when:
- The Kami has good stats/skills worth preserving
- You have 33+ Onyx Shards and can afford the investment
- You need this Kami for active plans (harvesting, quests)

Leave dead when:
- The Kami has poor stats and you plan to sacrifice/replace it
- Onyx Shards are scarce and needed for other purposes
- You have other Kamis that can cover the workload

## Revival

System: `system.kami.onyx.revive` (Operator wallet)

### Cost and Effect

| Resource | Amount |
|---|---|
| Onyx Shards (item 100) | **33** |

Post-revival state:
- State: `RESTING`
- HP: **33** (regardless of max HP)
- All other stats unchanged
- Immediately begins passive healing

### Post-Revival Plan

After reviving at 33 HP, the Kami needs healing time before harvesting:

| Harmony | Hours to reach 50% of 50 max HP (from 33) | Action |
|---|---|---|
| 10 | ~0.9 h | Wait, then short harvest session |
| 20 | ~0.7 h | Wait, then moderate harvest session |

If max HP is higher than 50 (from boosts), healing takes proportionally longer.

## HP Action Thresholds

These thresholds apply to **projected** HP (not on-chain sync value):

| Projected HP (% of max) | Action |
|---|---|
| > 50% | Safe. Continue harvesting or start a new session |
| 30–50% | Collect bounty now. Consider stopping if low Harmony |
| 15–30% | **Stop immediately**. Liquidation danger |
| < 15% | **Emergency stop**. Death imminent |
| = 0 | Dead. Decide: revive or leave |

## Cooldown Interaction

After most actions (collect, stop, level up, equip), a **180-second** base
cooldown applies. Factor this into heal timing — you can't restart harvesting
until cooldown expires.

See [accounts.md](accounts.md) for cooldown details.

## Cross-References

- Harvest strain formula: [harvesting.md](harvesting.md)
- HP projection between syncs: [state-reading.md](state-reading.md)
- Skills that improve healing: [leveling.md](leveling.md) (Enlightened/Guardian trees)
- Liquidation risk at low HP: [liquidation.md](liquidation.md)

## How to Execute

**Revive** — `system.kami.onyx.revive`
```
executeTyped(uint32 kamiIndex)
```
- Wallet: **Operator**
- Kami must be `DEAD`
- Deducts 33 Onyx Shards, sets state to `RESTING`, heals 33 HP
