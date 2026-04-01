# Factions & Reputation — Agent Decision Guide

Reputation strategy, faction quest priority.

## Factions

| Index | Name | Key | Description |
|---|---|---|---|
| 1 | The Agency | Agency | Relationship with the world administrators (the Menu) |
| 2 | The Elders | Mina | Relationship with Mina and her business/investors |
| 3 | The Nursery | Nursery | Relationship with the Nursery and its mysterious forces |

## Reputation Sources

Reputation is gained primarily through **quest rewards**:

| Faction | Quest Type | Rep per Quest |
|---|---|---|
| Agency | Main story quests (MENU) | 2, 4, or 6 |
| Elders (Mina) | Mina's faction quests (2001–2016) | 2, 4, or 6 |
| Nursery | Specific quests | 4 |

Reputation values vary per quest — check quest reward data for exact amounts.

## Reputation Tracking

Reputation is tracked as a **leaderboard score** per account per faction:

```
reputationId = keccak256("faction.reputation", accountId, factionIndex)
```

Reputation can be read via the score system's `Value` component.

## Decision Rules

### Priority

1. **Agency reputation** — comes naturally from main quest progression.
   No special effort needed; just keep completing main quests
2. **Elders (Mina) reputation** — requires accepting and completing Mina's
   faction quests (2001–2016). These unlock through main quest requirements
3. **Nursery reputation** — from specific quest rewards

### Strategy

- **Don't delay main quests** for faction reputation — Agency rep comes
  automatically from the main chain
- **Accept faction quests** as soon as they unlock (after meeting main quest
  prerequisites)
- **Repeatable faction quests** are the best way to farm reputation if
  available

### Quest-Gated Content

> HEURISTIC: some quests or goals may eventually gate on reputation
> thresholds, but no specific threshold values are currently known.
> Build reputation passively through quest completion — don't grind it
> speculatively.

## NPC Faction Assignment

NPCs belong to factions (tracked via `IndexFaction` component). This
determines which faction their quests serve. Not directly actionable by
the agent, but useful context for understanding quest givers.

## How to Read Reputation

```javascript
const repId = BigInt(ethers.keccak256(ethers.solidityPacked(
  ["string", "uint256", "uint32"],
  ["faction.reputation", accountId, factionIndex]
)));
const repValue = await valueComp.getValue(repId);
```

## Cross-References

- Faction quests: [quests.md](quests.md)
- Main quest chain (Agency rep source): [quests.md](quests.md)
