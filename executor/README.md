# Kamigotchi MCP Executor

The agent's **muscle**. An MCP server that reads private keys from `.env`
and exposes game actions as tools. The LLM (brain) never sees secrets.

```
Claude Code (brain) --MCP--> executor (muscle) ---> Kamibots API
                                                 \-> Yominet RPC
```

## How it works

- **Brain** (Claude Code): reads game context from this repo, reasons about
  what to do, calls MCP tools to act
- **Muscle** (this server): holds API keys and wallet keys, injects auth
  headers, signs transactions, returns results
- **Security boundary**: a PreToolUse hook blocks the LLM from reading `.env`.
  The LLM interacts with the game exclusively through MCP tools.

## Setup

```bash
cd executor
pip install -r requirements.txt
```

Copy and fill in the env template:
```bash
cp ../.env.template ../.env
# Edit ../.env with your keys
```

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

Add this to your Claude Code MCP settings (`.claude/settings.json` or
the global Claude Code config).

## Available tools

### Kamibots API (state reads)

| Tool | Description |
|---|---|
| `get_tier()` | Account tier, tax rate, slot usage |
| `get_inventory()` | All items and balances |
| `get_kami_state(kami_id)` | Full kami data (stats, bonuses, harvest) |
| `get_kami_state_slim(kami_id)` | Lightweight kami data |
| `get_all_strategies()` | List active strategies |
| `get_strategy_status(kami_id)` | Single strategy status |
| `get_strategy_logs(container_id, tail)` | Strategy container logs |
| `get_prices()` | Marketplace item prices |
| `get_npc_prices()` | NPC shop prices |
| `get_nodes()` | All harvest nodes |
| `get_account_kamis(address)` | Kamis by operator address |

### Kamibots API (strategy execution)

| Tool | Description |
|---|---|
| `start_strategy(type, kami_id, node_id, config)` | Start a strategy |
| `stop_strategy(kami_id)` | Stop a running strategy |

### On-chain (direct transactions)

| Tool | Description |
|---|---|
| `move_to_room(room_index)` | Move account to a room |
| `feed_kami(kami_id, food_item_id)` | Feed kami to restore HP |
| `revive_kami(kami_id)` | Revive dead kami (33 Onyx) |
| `level_up_kami(kami_id)` | Level up if XP sufficient |
| `equip_item(kami_id, item_index)` | Equip item to kami |
| `unequip_item(kami_id, slot_type)` | Unequip from slot |

## Adding new tools

1. Identify the system ID from `integration/system-ids.md`
2. Get the ABI from `integration/api/<system>.md`
3. Add the ABI constant and `@mcp.tool()` function to `server.py`
4. For Kamibots API tools: use `_api_get`/`_api_post`/`_api_delete`
5. For on-chain tools: use `_send_tx(system_id, abi, args, gas_limit)`

Entity ID derivation: kami token index -> entity ID via `_kami_entity_id()`.
See `integration/entity-ids.md` for other entity types.
