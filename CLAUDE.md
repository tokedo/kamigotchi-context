# CLAUDE.md — Agent Context Builder                             
                                                                                                                        
  ## What This Project Is                                                                                               
   
  This repo contains **decision-oriented game context** for AI agents that play
  Kamigotchi — a pure on-chain MMORPG on Yominet. It is self-contained: the
  playing agent reads only files in this repo. The content was distilled from
  the technical GDD at [`kamigotchi-gdd`](https://github.com/tokedo/kamigotchi-gdd)
  (used by the context builder, not by the playing agent).                                                                                                   
                                                                                                                        
  ## Your Role                                                                                                          
                                                                                                                        
  You are building context files that help an AI agent make optimal in-game                                             
  decisions. You are NOT writing player tutorials or technical docs.
                                                                                                                        
  ## Source of Truth

  **For the playing agent**: this repo's `systems/`, `catalogs/`, and
  `strategies/` files are the complete source of truth. The agent should never
  need to read external repos — all decision-relevant mechanics, formulas,
  thresholds, and calibrated heuristics are distilled here.

  **For the context builder** (you, when updating this repo):
  - **GDD repo**: [`kamigotchi-gdd`](https://github.com/tokedo/kamigotchi-gdd) — raw mechanics, formulas, source citations
  - **Game source code**: `https://github.com/Asphodel-OS/kamigotchi`
  - Read GDD files to verify formulas, then distill into agent-oriented `systems/` files.

  ## Writing Rules

  1. **Decision-first**: every section should answer "what should the agent do?"
  2. **Terse**: no narrative, no flavor text, no "in Kamigotchi, players can..."
  3. **Conditional**: use "if X, then Y" patterns, not prose descriptions
  4. **Quantitative**: include exact thresholds, ratios, and formulas that affect decisions
  5. **Self-contained**: all decision-relevant formulas must be present in this repo. Never link to external repos for formulas — the playing agent only reads files in this repo
  6. **State-aware**: describe what game state the agent should check before acting
  7. README.md is the entry point — it must fit in ~2-3 pages and link to everything
  8. System files go in `systems/`, catalogs in `catalogs/`, strategy files in `strategies/`
  9. Mark any uncertain decision heuristics with `> HEURISTIC:` — needs playtesting
  10. Catalogs are CSV with a comment header explaining key columns and decision relevance

  ## Strategy Promotion

  Strategy files in `strategies/` capture proven decision patterns from the
  calibration loop (see [systems/memory.md](systems/memory.md)).

  **When to promote**: a decision pattern from `memory/decisions.md` generalizes
  beyond its specific situation AND has been confirmed by human review.

  **What a strategy file contains**:
  - The decision pattern — conditional, terse ("if X, then Y")
  - Why it works — the game mechanic reasoning behind it
  - When to apply — the conditions that trigger this pattern
  - When NOT to apply — edge cases, exceptions, changed assumptions

  **Confidence markers**:
  - `> CALIBRATED: confirmed by human review on <YYYY-MM-DD>` — tested and validated
  - `> CANDIDATE: proposed on <YYYY-MM-DD>, awaiting review` — agent-proposed, not yet confirmed

  Keep the same writing style as `systems/` files: terse, conditional,
  quantitative. No narrative. Update `strategies/INDEX.md` whenever a strategy
  file is added or updated.

  ## Integration Layer

  On-chain interaction docs live in `integration/`. When updating integration
  files, the source is:
  - **Game source code**: [`kamigotchi`](https://github.com/Asphodel-OS/kamigotchi) — canonical contract logic, ABI extraction

  Key facts:
  - Chain: **Yominet** (Chain ID `428962654539583`)
  - RPC: `https://jsonrpc-yominet-1.anvil.asia-southeast.initia.xyz`
  - World contract: `0x2729174c265dbBd8416C6449E0E813E88f43D0E7`
  - Gas: flat `0.0025 gwei` — cost is negligible, but gas **limits** matter for complex calls
  - Dual wallet model: **Owner** (registers, trades, mints, approvals) vs **Operator** (gameplay: harvest, move, equip, quests)

  ### File Map

  | Need… | Read… |
  |---|---|
  | Chain ID, RPC, gas, currencies | [integration/chain.md](integration/chain.md) |
  | World address, token contracts, system resolution | [integration/addresses.md](integration/addresses.md) |
  | All 67 system IDs + wallet requirements | [integration/system-ids.md](integration/system-ids.md) |
  | Entity ID derivation (account, kami, harvest, etc.) | [integration/entity-ids.md](integration/entity-ids.md) |
  | ethers.js setup, provider, signer patterns | [integration/sdk-setup.md](integration/sdk-setup.md) |
  | First-time bootstrap (register, fund, mint) | [integration/bootstrap.md](integration/bootstrap.md) |
  | Per-system call signatures + code examples | `integration/api/<system>.md` |
  | ABI JSON for any system/component | `integration/abi/<Name>.json` |
  | MUD ECS architecture overview | [integration/architecture.md](integration/architecture.md) |
  | Common errors and troubleshooting | [integration/errors.md](integration/errors.md) |
  | Game data tables (nodes, rooms, items) | [integration/game-data.md](integration/game-data.md) |
  | Complete synced world state (MUD indexer) | [integration/sync/](integration/sync/) |
  | Kamibots API reference (V1 primary) | [integration/kamibots/](integration/kamibots/) |
  | MCP executor (game action tools) | [executor/](executor/) |

  ## Memory System

  The agent is a **multi-account mastermind** controlling 1–N accounts.
  Persistent state lives in `memory/` (gitignored).
  See [systems/memory.md](systems/memory.md) for the full specification.

  On session start:
  0. Verify the local MUD sync is running (`curl http://localhost:3001/health`).
     If not, start it: `cd integration/sync && ./setup.sh`.
     The sync provides efficient world state reads for all perception queries.
  1. `systems/memory.md` — understand the memory schema
  2. `strategies/INDEX.md` — calibrated decision patterns (read before planning)
  3. `memory/accounts/INDEX.md` — account roster (labels, roles, wallets)
  4. `memory/accounts/<label>.md` — per-account snapshots
  5. `memory/plans/INDEX.md` — current plan tree (portfolio → strategic → tactical → routine)

  If `memory/` is empty or missing, this is a cold start — perceive all
  accounts, assign roles, and run a plan revision session to initialize.

  ## Playing Agent (Private Fork)

  When this repo is cloned as a private fork for gameplay, the agent
  operates through an MCP server that handles secrets and signing.

  ### Setup (one-time)

  1. Clone this repo as a private fork
  2. `cp .env.template .env` — fill in per-account private keys
     (`MAIN_OPERATOR_KEY`, `MAIN_OWNER_KEY`, etc.)
  3. `cp accounts/roster.yaml.template accounts/roster.yaml` — fill in
     matching public addresses for each label
  4. `cp .claude/settings.json.template .claude/settings.json` — enables
     the PreToolUse hook that blocks .env access
  5. `cd executor && pip install -r requirements.txt`
  6. Configure Claude Code MCP server pointing at `executor/server.py`

  ### Key management

  Private keys and public addresses are split across two files:

  | File | Contains | Visible to LLM | Git |
  |---|---|---|---|
  | `.env` | `{LABEL}_OPERATOR_KEY`, `{LABEL}_OWNER_KEY`, auto-populated API creds | No | gitignored |
  | `accounts/roster.yaml` | Labels, owner addresses, operator addresses | Yes | committed |

  Labels must match between the two files (e.g., `MAIN_OPERATOR_KEY`
  in `.env` ↔ `main:` in `roster.yaml`). The MCP server cross-references
  on startup and warns on mismatches.

  `KAMIBOTS_API_KEY` and `PRIVY_ID` in `.env` are auto-populated by the
  `register_kamibots` tool — do not fill manually.

  ### Security Rules

  - **NEVER** attempt to read `.env` — the PreToolUse hook will block it.
    All secrets are handled by the MCP server.
  - **ALL** game actions go through MCP tools. Do not construct raw API
    calls or transactions.
  - Private keys exist only inside the MCP server process. The LLM
    interacts with the game exclusively through tool calls.
  - `accounts/roster.yaml` is safe to read — it contains only public
    addresses. This is the agent's view of "which accounts do I manage."
  - `.env`, `memory/`, `.claude/settings.json` are gitignored.

  ### Session Protocol

  Each session follows this loop:

  1. **Read roster** — `accounts/roster.yaml` for account labels + addresses
  2. **Read memory** — `memory/` snapshots and plans
  3. **Perceive** — call MCP tools: `list_accounts()`,
     `get_tier(account=...)`, `get_kami_state(kami_id, account=...)`,
     `get_inventory(account=...)`, `get_all_strategies(account=...)`
  4. **Plan** — compare current state against strategies and goals
  5. **Act** — call MCP tools: `start_strategy(...)`, `feed_kami(...)`,
     `move_to_room(...)`, etc. — always passing the `account` label
  6. **Record** — update `memory/` with new snapshots and decisions

  ### Onboarding (first session)

  1. Call `list_accounts()` — see what accounts are configured
  2. If Kamibots not registered: call `register_kamibots(account="main")`
  3. Call `store_operator_key(account=...)` for each account
  4. Call `get_tier(account=...)` to verify API access
  5. Call `get_account_kamis(account=...)` for each account to discover kamis
  6. Update `accounts/roster.yaml` with discovered kami data
  7. Run initial perception and create first plans in `memory/`

  ### MCP Tools Reference

  See [executor/README.md](executor/README.md) for the full tool list.
  All per-account tools accept `account="main"` (default).

  Key tools:
  - **Setup**: `list_accounts`, `register_kamibots`, `store_operator_key`
  - **Reads**: `get_tier`, `get_inventory`, `get_kami_state`,
    `get_kami_state_slim`, `get_nodes`, `get_prices`, `get_npc_prices`
  - **Strategies**: `start_strategy`, `stop_strategy`,
    `get_all_strategies`, `get_strategy_status`, `get_strategy_logs`
  - **On-chain**: `move_to_room`, `feed_kami`, `revive_kami`,
    `level_up_kami`, `equip_item`, `unequip_item`
