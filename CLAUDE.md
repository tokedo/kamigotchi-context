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

  **For the playing agent**: this repo's `systems/` and `catalogs/` files are
  the complete source of truth. The agent should never need to read external
  repos — all decision-relevant mechanics, formulas, and thresholds are
  distilled here.

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
  8. System files go in `systems/`, catalogs in `catalogs/`, strategy guides in `strategies/`
  9. Mark any uncertain decision heuristics with `> HEURISTIC:` — needs playtesting
  10. Catalogs are CSV with a comment header explaining key columns and decision relevance

  ## Integration Layer

  On-chain interaction docs live in `integration/`. Sources:
  - **kamigotchi-docs** (Asphodel-OS) — player API, architecture, game data
  - **kamigotchi-abis** — ABI JSONs extracted from contract source

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

  ## Memory System

  The agent is a **multi-account mastermind** controlling 1–N accounts.
  Persistent state lives in `memory/` (gitignored).
  See [systems/memory.md](systems/memory.md) for the full specification.

  On session start, always read:
  1. `systems/memory.md` — understand the memory schema
  2. `memory/accounts/INDEX.md` — account roster (labels, roles, wallets)
  3. `memory/accounts/<label>.md` — per-account snapshots
  4. `memory/plans/INDEX.md` — current plan tree (portfolio → strategic → tactical → routine)

  If `memory/` is empty or missing, this is a cold start — perceive all
  accounts, assign roles, and run a plan revision session to initialize.
