# Local MUD Sync — World State Indexer

The agent's "eyes." A background process that subscribes to every Yominet
block, captures all `Store_SetRecord` events from the World contract, and
maintains a complete copy of game state in a local PostgreSQL database.

Once running, the agent can answer questions like "who is harvesting on
node 14?" or "list all Kamis in room 66" with a single SQL query instead
of scanning individual entities via RPC.

## Architecture

```
Yominet RPC ──► MUD store-indexer ──► PostgreSQL ──► Agent queries
 (blocks)      (postgres-decoded)    (per-table       (SQL or
                                      schemas)       REST API)
```

- **MUD store-indexer** (`@latticexyz/store-indexer`) watches the World
  contract and writes decoded table data to PostgreSQL.
- **postgres-decoded mode** creates a PostgreSQL schema per World address
  with a table per MUD table — directly queryable with SQL.
- The indexer also exposes a **REST API** on port 3001 for programmatic
  queries (`GET /api/logs`).

## Raw ECS vs Game State

The MUD sync gives you **raw ECS component tables** — the same data the
blockchain stores. This is NOT directly game-meaningful state. Examples:

| Sync gives you | Agent needs |
|---|---|
| `health: [base=50, shift=-5, boost=0, sync=38]` | "Kami #3 has ~32 projected HP" |
| `state: 2` | "Kami #3 is HARVESTING" |
| Harvest entity with `start_time`, `node_index` | "Kami #3 has earned ~45 Musu, strain is 12 HP" |

Translating raw ECS into game-meaningful state requires a **game logic
interpretation layer** — the same business logic the web client runs in
the browser. The formulas and logic are all documented in `systems/`
files ([state-reading.md](../../systems/state-reading.md) has projection
formulas, [harvesting.md](../../systems/harvesting.md) has bounty/strain
math) — that's the spec. Implementation is future work.

**For v1**: use the [Kamibots read APIs](../kamibots/) for pre-computed
game state (projected HP, earnings, strategy status). Use the raw MUD
sync for aggregate queries the Kamibots API doesn't cover (like node
occupancy across the whole world).

## What becomes available

With the sync running, the agent has a complete, continuously-updated
mirror of all on-chain game state:

| Data | How to query |
|---|---|
| Every Kami's state, stats, level, room | SQL on decoded tables |
| Every account's inventory, stamina, room | SQL on decoded tables |
| Node occupancy (all active harvesters) | SQL join harvest + node tables |
| All harvest entities with start times | SQL on harvest tables |
| Quest progress, equipment, trade orders | SQL on respective tables |
| Aggregate queries (counts, rankings) | Standard SQL aggregation |

**Note:** HP, stamina, and bounty values are lazy-synced on-chain. The
sync gives the last-synced snapshot. Between actions, project forward
using the formulas in [systems/state-reading.md](../../systems/state-reading.md).

## Prerequisites

**Option A — Docker (recommended):**
- Docker Engine 20+ and Docker Compose v2
- ~1 GB disk for PostgreSQL data

**Option B — Node.js (manual):**
- Node.js 18+ and pnpm (or npx)
- PostgreSQL 14+ running locally

## Quick Start (Docker)

```bash
cd integration/sync
cp .env.example .env    # edit if needed — defaults work for Kamigotchi
docker compose up -d
```

Or use the bootstrap script:

```bash
cd integration/sync
chmod +x setup.sh
./setup.sh
```

The setup script checks prerequisites, creates `.env`, starts services,
waits for initial sync, and runs a smoke test.

## Quick Start (Node.js)

If not using Docker, ensure PostgreSQL is running and accessible:

```bash
# Install and run directly
npx -y -p @latticexyz/store-indexer postgres-decoded-indexer

# Required env vars:
export RPC_HTTP_URL="https://jsonrpc-yominet-1.anvil.asia-southeast.initia.xyz"
export DATABASE_URL="postgres://kamigotchi:kamigotchi@localhost:5432/kamigotchi"
export STORE_ADDRESS="0x2729174c265dbBd8416C6449E0E813E88f43D0E7"
export FOLLOW_BLOCK_TAG="latest"
```

Then start the frontend API separately:

```bash
npx -y -p @latticexyz/store-indexer postgres-frontend
# Serves REST API on port 3001
```

> Since `@latticexyz/store-indexer` v2.2.18, `pnpm start:postgres-decoded`
> runs both the indexer backend and frontend concurrently. The Docker
> image uses this combined command.

## Verify the Sync

1. **Health check:**
   ```bash
   curl http://localhost:3001/health
   ```
   Returns ready status when the indexer is caught up.

2. **REST API test:**
   ```bash
   curl "http://localhost:3001/api/logs?input=$(python3 -c "import urllib.parse,json; print(urllib.parse.quote(json.dumps({'chainId':428962654539583,'address':'0x2729174c265dbBd8416C6449E0E813E88f43D0E7','filters':[]})))")"
   ```
   Should return `{ blockNumber: "...", logs: [...] }`.

3. **Direct SQL test:**
   ```bash
   docker compose exec postgres psql -U kamigotchi -d kamigotchi -c "\dn"
   ```
   Should show a schema named `0x2729174c265dbBd8416C6449E0E813E88f43D0E7`.

4. **List all synced tables:**
   ```bash
   docker compose exec postgres psql -U kamigotchi -d kamigotchi -c \
     "SELECT table_name FROM information_schema.tables WHERE table_schema = '0x2729174c265dbBd8416C6449E0E813E88f43D0E7';"
   ```

## Configuration

All config is via environment variables. See [.env.example](.env.example)
for defaults. Key settings:

| Variable | Default | Notes |
|---|---|---|
| `RPC_HTTP_URL` | Yominet RPC | At least one of HTTP or WS required |
| `STORE_ADDRESS` | World contract | Omit to index all MUD Stores on chain |
| `FOLLOW_BLOCK_TAG` | `latest` | Use `latest` for Yominet (no `safe`/`finalized` support) |
| `START_BLOCK` | `0` | Set to World deployment block for faster initial sync |
| `MAX_BLOCK_RANGE` | `1000` | Blocks per `eth_getLogs` call |
| `POLLING_INTERVAL` | `1000` | Milliseconds between polls |

## Querying

See [query-examples.md](query-examples.md) for SQL and REST API patterns
mapped to agent decision needs.

## Troubleshooting

- **Indexer exits immediately**: check `DATABASE_URL` — PostgreSQL must be
  reachable. Run `docker compose logs indexer` to see errors.
- **Tables empty after startup**: initial sync takes time depending on
  chain history. Check `docker compose logs -f indexer` for block progress.
- **`FOLLOW_BLOCK_TAG` errors**: Yominet may not support `safe` or
  `finalized` tags. Use `latest`.
- **Platform mismatch (Apple Silicon)**: the Docker image is `linux/amd64`.
  Docker Desktop handles emulation automatically, but add
  `platform: linux/amd64` to docker-compose if you see issues.
