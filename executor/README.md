# Kamigotchi MCP Executor

The agent's **muscle**. An MCP server that reads private keys from
`~/.blocklife-keys/.env` (outside the repo) and exposes game actions
as tools. The LLM (brain) never sees secrets.

```
Claude Code (brain) --MCP--> executor (muscle) ---> Kamibots API
                                                 \-> Yominet RPC
```

## Account labeling system

Each account has a **label** (e.g., `main`, `farm1`). The label ties
together private keys in `.env` and public addresses in `roster.yaml`:

| File | Contains | Visible to LLM |
|---|---|---|
| `~/.blocklife-keys/.env` | `{LABEL}_OPERATOR_KEY`, `{LABEL}_OWNER_KEY` | No (outside repo, hook-blocked) |
| `accounts/roster.yaml` | Label, owner address, operator address | Yes (committed) |

Keys live **outside the project directory** at `~/.blocklife-keys/.env`.
Claude Code auto-indexes files in the working directory on startup — by
keeping keys external, there is nothing sensitive to discover.

On startup, the server scans `~/.blocklife-keys/.env` for all
`*_OPERATOR_KEY` / `*_OWNER_KEY` pairs, builds an account registry,
and cross-references with `roster.yaml` (warns on mismatches).

All per-account tools accept an `account` parameter (default `"main"`).

## Setup

```bash
cd executor
pip install -r requirements.txt
```

## Initialization flow

1. **Create keys file** outside the repo:
   ```bash
   mkdir -p ~/.blocklife-keys
   cp env.template ~/.blocklife-keys/.env
   # Edit ~/.blocklife-keys/.env: set MAIN_OPERATOR_KEY, MAIN_OWNER_KEY, etc.
   ```

2. **Fill `roster.yaml`** with public addresses:
   ```bash
   cp accounts/roster.yaml.template accounts/roster.yaml
   # Edit: set owner_address and operator_address for each label
   ```

3. **Start MCP server** (via Claude Code config)

4. **Register with Kamibots** (agent calls once):
   ```
   register_kamibots(account="main")
   ```
   Signs with the owner wallet, saves API key + privy_id to `.env`.

5. **Store operator key** (agent calls per account):
   ```
   store_operator_key(account="main")
   store_operator_key(account="farm1")
   ```
   Sends each operator key to Kamibots (encrypted at rest).

6. **Ready to play** — all other tools now work.

## Running

The server runs as a stdio MCP server, launched by Claude Code:

```json
{
  "mcpServers": {
    "kamigotchi": {
      "command": "python",
      "args": ["executor/server.py"],
      "cwd": "/path/to/kamigotchi-context"
    }
  }
}
```

## Available tools

### Account management

| Tool | Description |
|---|---|
| `list_accounts()` | Labels + public addresses, registration status |
| `register_kamibots(account)` | Register with Kamibots API (owner wallet signature) |
| `store_operator_key(account)` | Send operator key to Kamibots (encrypted) |

### Kamibots API (state reads)

| Tool | Description |
|---|---|
| `get_tier(account)` | Account tier, tax rate, slot usage |
| `get_inventory(account)` | All items and balances |
| `get_kami_state(kami_id, account)` | Full kami data (stats, bonuses, harvest) |
| `get_kami_state_slim(kami_id, account)` | Lightweight kami data |
| `get_kamis_progress_batch(kami_ids, account)` | Compact level/XP/skills for many kamis |
| `get_all_strategies(account)` | List active strategies |
| `get_strategy_status(kami_id, account)` | Single strategy status |
| `get_strategy_logs(container_id, tail, account)` | Strategy container logs |
| `get_prices()` | Marketplace item prices (global) |
| `get_npc_prices()` | NPC shop prices (global) |
| `get_nodes()` | All harvest nodes (global) |
| `get_killer_ranking(account)` | Top predator kamis by kill count (1h cache) |
| `get_leaderboard(type, account)` | Leaderboards: 'harvest' or 'kill' (20m cache) |
| `get_all_kamis(account)` | All kamis in game: index, name, state (24h cache) |
| `get_account_kamis(account, address)` | Kamis by address |

### Kamibots API (strategy execution)

| Tool | Description |
|---|---|
| `start_strategy(type, kami_id, node_id, config, account)` | Start a strategy |
| `stop_strategy(kami_id, permanent, account)` | Stop/pause a running strategy |

### On-chain (direct transactions)

| Tool | Description |
|---|---|
| `harvest_start(kami_ids, node_index, account)` | Start harvesting (single or batch) |
| `harvest_stop(kami_ids, account)` | Stop harvests + auto-collect rewards (batch) |
| `harvest_collect(kami_ids, account)` | Collect rewards without stopping (batch) |
| `move_to_room(room_index, account)` | Single-hop move to adjacent room |
| `travel_to_room(target_room, account, use_items, dry_run)` | Multi-hop autopilot with BFS pathfinding + stamina management |
| `listing_buy(merchant_index, item_indices, amounts, account)` | Buy items from NPC merchant |
| `feed_kami(kami_id, food_item_id, account)` | Feed kami to restore HP |
| `revive_kami(kami_id, account)` | Revive dead kami (33 Onyx) |
| `level_up_kami(kami_id, account)` | Level up if XP sufficient |
| `equip_item(kami_id, item_index, account)` | Equip item to kami |
| `unequip_item(kami_id, slot_type, account)` | Unequip from slot |
| `use_account_item(item_id, account, amount)` | Use consumable on account (stamina restores, etc.) |
| `burn_items(item_indices, amounts, account)` | Burn/destroy items (for quest turn-ins) |

### Quest management

| Tool | Description |
|---|---|
| `get_active_quests(account)` | Enumerate all active quests (on-chain read) |
| `get_quest_status(quest_index, account)` | Check quest state string |
| `accept_quest(quest_index, account)` | Accept a quest |
| `complete_quest(quest_index, account)` | Complete an active quest |
| `check_quest_completable(quest_index, account)` | Free check if objectives are met (no gas) |
| `drop_quest(quest_index, account)` | Drop/abandon an active quest |

### Scavenge & droptable

| Tool | Description |
|---|---|
| `get_scavenge_points(node_index, account)` | Check accumulated scavenge points |
| `scavenge_claim(node_index, account)` | Claim scavenge rewards (returns commit_ids) |
| `droptable_reveal(commit_ids, account)` | Reveal droptable commits to receive items |
| `scavenge_claim_and_reveal(node_index, account)` | Combined claim + wait + reveal |

### Batch / composite tools

| Tool | Description |
|---|---|
| `get_kamis_progress_batch(kami_ids, account)` | Compact level/XP/skills for N kamis in one call |
| `level_and_allocate_batch(targets, account)` | Batch level-up + skill allocation across many kamis |
| `level_to(kami_id, target_level, account)` | Level up repeatedly to target |
| `allocate_skills(kami_id, skill_plan, account)` | Allocate multiple skill points |
| `use_item_batch(kami_id, item_id, count, account)` | Use same item N times |

## Adding new tools

1. Identify the system ID from `integration/system-ids.md`
2. Get the ABI from `integration/api/<system>.md`
3. Add the ABI constant and `@mcp.tool()` function to `server.py`
4. For Kamibots API tools: use `_api_get`/`_api_post`/`_api_delete`
5. For on-chain tools: use `_send_tx(account, system_id, abi, args)`
6. Add `account: str = "main"` parameter to all per-account tools

Entity ID derivation: kami token index -> entity ID via `_kami_entity_id()`.
See `integration/entity-ids.md` for other entity types.
