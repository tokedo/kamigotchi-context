# NPC Shops & Auctions — Agent Decision Guide

Buying and selling items from NPCs, dynamic pricing, and global auctions.

## NPC Shops

NPCs sell and buy items at configurable prices. Must be in the **same room**
as the NPC to transact (unless NPC room = 0, meaning globally accessible).

### Pricing Strategies

#### FIXED

Flat price: `cost = pricePerUnit * amount`

Most sell-side listings use FIXED pricing.

#### GDA (Gradual Dutch Auction)

Dynamic pricing on the **buy side** — price rises with demand, decays over time.

```
spotPrice = targetPrice * decay^(timeDelta - prevSold / rate)
```

Where:
- `timeDelta = (now - startTimestamp) / period`
- `prevSold` = total units sold so far
- `decay` = price decay factor per period (< 1.0 means price drops over time)
- `rate` = expected purchases per period for equilibrium pricing

For multiple units:
```
c = decay^(-1/rate)
cost = spotPrice * (c^quantity - 1) / (c - 1)
```

**Behavior**: price starts at `targetPrice` and rises when buying outpaces the
rate. Price decays back down when buying slows. Wait for price to decay if it's
above target.

### Decision: When to Buy from NPC

- Compare GDA price to P2P trade alternatives
- If GDA price is above target → wait for decay (check back later)
- If GDA price is at or below target → buy now before others drive it up
- Factor in travel cost (stamina) to reach the NPC's room

### Decision: When to Sell to NPC

- NPC sell prices are typically FIXED — no timing advantage
- Compare to P2P trade value (NPC has no tax, but price may be lower)
- Sell excess items that aren't worth trading P2P

### Projecting GDA Price

The agent can compute current GDA price locally without an RPC call:

```
timeDelta = (nowTimestamp - startTimestamp) / period
spotPrice = targetPrice * decay^(timeDelta - prevSold / rate)
```

Read `Balance` (prevSold) and `TimeStart` from the listing entity.
See [state-reading.md](state-reading.md) for the projection formula.

## Newbie Vendor

One-time Kami purchase for new accounts.

### Eligibility

All must be true:
1. Account created within the last **24 hours**
2. Account has **not** previously purchased from the vendor
3. `NEWBIE_VENDOR_ENABLED` is true

### Price

```
price = max(twapPrice, minPrice)
```

- `minPrice` = 0.005 ETH (config `NEWBIE_VENDOR_MIN_PRICE`)
- `twapPrice` = time-weighted average of recent Kami marketplace sales

### Pool

The vendor shows **3 Kamis** from a rotating pool. Display rotates every
48 hours (config `NEWBIE_VENDOR_CYCLE`). Purchased Kamis are removed from pool.

### Restrictions

- Purchased Kami is **soulbound for 3 days** (can't list, unstake, or accept offers)
- Only 1 purchase per account, ever

### Decision: Should a New Account Buy?

- **Yes** if the price is below marketplace floor — guaranteed good deal
- Check the 3 displayed Kamis' stats/affinities before buying
- The soulbind prevents flipping but doesn't restrict gameplay (harvest, equip, etc.)

## Global Auctions

System-level item sales using GDA pricing. Not room-gated.

### Current Auctions

| Auction | Item Sold | Currency | Supply | Target Price | Period | Decay | Rate |
|---|---|---|---|---|---|---|---|
| Gacha ↔ Musu | Gacha Ticket (10) | Musu (1) | 17,222 | 32,000 Musu | 1 day | 0.75 | 32/day |
| Reroll ↔ Onyx | Reroll Token (11) | Onyx (100) | 100,000 | 50 Onyx | 1 day | 0.5 | 16/day |

System: `system.auction.buy`
```
executeTyped(uint32 itemIndex, uint256 amount)
```

### Decision: When to Buy from Auction

**Gacha Tickets** (alternative to NPC shop):
- If auction price < NPC shop price → buy from auction
- If auction price is spiked (heavy recent buying) → wait for decay
- 32,000 Musu target price at equilibrium — compare to your income rate

**Reroll Tokens**:
- 50 Onyx target price at equilibrium
- Only buy if you have a Kami worth rerolling (poor stats)
- Compare cost of reroll vs just minting new

### Price Timing

Both auctions use decay factors < 1.0, so price drops over time when nobody
buys. Best strategy:

1. Check current price locally (same GDA formula)
2. If price > 1.5x target → wait
3. If price <= target → buy
4. If you urgently need the item → buy regardless of premium

## How to Execute

### NPC Shop

**Buy** — `system.listing.buy` (Operator wallet)
```
executeTyped(uint32 merchantIndex, uint32[] itemIndices, uint256[] amounts)
```
Must be in same room as NPC (or NPC room = 0).

**Sell** — `system.listing.sell` (Operator wallet)
```
executeTyped(uint32 merchantIndex, uint32[] itemIndices, uint256[] amounts)
```
Same room requirement.

### Auction

**Buy** — `system.auction.buy` (Operator wallet)
```
executeTyped(uint32 itemIndex, uint256 amount)
```
No room requirement. May have conditional requirements.

## Cross-References

- Shop listings: [catalogs/shop-listings.csv](../catalogs/shop-listings.csv)
- P2P trading (alternative): [trading.md](trading.md)
- GDA price projection: [state-reading.md](state-reading.md)
- Gacha system (what tickets do): [gacha.md](gacha.md)
