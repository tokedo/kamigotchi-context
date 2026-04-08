"""
Kamigotchi MCP Executor — the agent's muscle.

Reads private keys from ~/.blocklife-keys/.env (outside the repo).
Exposes game actions as MCP tools. The LLM (brain) calls tools through
Claude Code; this server (muscle) handles secrets, API auth, and
transaction signing. The LLM never sees private keys.

Multi-account: keys file holds {LABEL}_OPERATOR_KEY / {LABEL}_OWNER_KEY
pairs. accounts/roster.yaml (in-repo) maps labels to public addresses.
All per-account tools accept an `account` label parameter (default "main").

Architecture:
  Claude Code (brain) --MCP--> executor (muscle) ---> Kamibots API / Yominet RPC
"""

import json
import os
import time
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv, set_key
from eth_account.messages import encode_defunct
from mcp.server.fastmcp import FastMCP
from web3 import Web3

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parent.parent
_KEYS_PATH = Path.home() / ".blocklife-keys" / ".env"
_ROSTER_PATH = _REPO / "accounts" / "roster.yaml"

load_dotenv(_KEYS_PATH)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KAMIBOTS_BASE = "https://api.kamibots.xyz"
WORLD_ADDRESS = Web3.to_checksum_address(
    "0x2729174c265dbBd8416C6449E0E813E88f43D0E7"
)
CHAIN_ID = 428962654539583
RPC_URL = os.environ.get(
    "RPC_URL", "https://jsonrpc-yominet-1.anvil.asia-southeast.initia.xyz"
)

# ---------------------------------------------------------------------------
# Web3
# ---------------------------------------------------------------------------

w3 = Web3(Web3.HTTPProvider(RPC_URL))
_GAS_PRICE = {"maxFeePerGas": 2_500_000, "maxPriorityFeePerGas": 0}

_WORLD_ABI = json.loads(
    '[{"type":"function","name":"systems","inputs":[],'
    '"outputs":[{"type":"address"}],"stateMutability":"view"}]'
)
_SYSTEMS_COMPONENT_ABI = json.loads(
    '[{"type":"function","name":"getEntitiesWithValue",'
    '"inputs":[{"name":"v","type":"uint256"}],'
    '"outputs":[{"type":"uint256[]"}],"stateMutability":"view"}]'
)
_world = w3.eth.contract(address=WORLD_ADDRESS, abi=_WORLD_ABI)
_system_cache: dict[str, str] = {}


def _resolve_system(system_id: str) -> str:
    """Resolve system ID string to on-chain contract address (cached)."""
    if system_id not in _system_cache:
        h = int.from_bytes(Web3.keccak(text=system_id), "big")
        sc_addr = _world.functions.systems().call()
        sc = w3.eth.contract(address=sc_addr, abi=_SYSTEMS_COMPONENT_ABI)
        entities = sc.functions.getEntitiesWithValue(h).call()
        if not entities:
            raise ValueError(f"System not found on-chain: {system_id}")
        addr = Web3.to_checksum_address(
            "0x" + hex(entities[0])[2:].zfill(40)[-40:]
        )
        _system_cache[system_id] = addr
    return _system_cache[system_id]


def _kami_entity_id(kami_index: int) -> int:
    """Derive kami entity ID from token index: keccak256("kami.id", index)."""
    return int.from_bytes(
        Web3.solidity_keccak(["string", "uint32"], ["kami.id", kami_index]), "big"
    )


# ---------------------------------------------------------------------------
# Account registry — loaded from .env + roster.yaml
# ---------------------------------------------------------------------------


class _Account:
    __slots__ = (
        "label", "operator_key", "owner_key", "operator_addr", "owner_addr",
        "api_key", "privy_id",
    )

    def __init__(
        self, label: str, operator_key: str, owner_key: str | None,
        api_key: str | None = None, privy_id: str | None = None,
    ):
        self.label = label
        self.operator_key = operator_key
        self.owner_key = owner_key
        self.operator_addr = w3.eth.account.from_key(operator_key).address
        self.owner_addr = (
            w3.eth.account.from_key(owner_key).address if owner_key else None
        )
        self.api_key = api_key
        self.privy_id = privy_id


_accounts: dict[str, _Account] = {}


def _load_accounts() -> None:
    """Scan .env for *_OPERATOR_KEY pairs, build account registry."""
    labels: set[str] = set()
    for key in os.environ:
        if key.endswith("_OPERATOR_KEY"):
            labels.add(key.removesuffix("_OPERATOR_KEY").lower())
        elif key.endswith("_OWNER_KEY"):
            labels.add(key.removesuffix("_OWNER_KEY").lower())

    for label in sorted(labels):
        up = label.upper()
        op_key = os.environ.get(f"{up}_OPERATOR_KEY")
        own_key = os.environ.get(f"{up}_OWNER_KEY")
        if not op_key:
            print(
                f"WARNING: {up}_OPERATOR_KEY missing, "
                f"skipping account '{label}'"
            )
            continue
        api_key = os.environ.get(f"{up}_KAMIBOTS_API_KEY")
        privy_id = os.environ.get(f"{up}_PRIVY_ID")
        _accounts[label] = _Account(label, op_key, own_key, api_key, privy_id)

    # Migrate legacy global credentials to first account that lacks them
    legacy_api = os.environ.get("KAMIBOTS_API_KEY")
    legacy_privy = os.environ.get("PRIVY_ID")
    if legacy_api or legacy_privy:
        for acct in _accounts.values():
            if not acct.api_key and legacy_api:
                acct.api_key = legacy_api
                print(f"NOTE: Migrated legacy KAMIBOTS_API_KEY to '{acct.label}'. "
                      f"Re-run register_kamibots(account='{acct.label}') to "
                      f"write {acct.label.upper()}_KAMIBOTS_API_KEY to .env.")
            if not acct.privy_id and legacy_privy:
                acct.privy_id = legacy_privy
                break  # only assign legacy creds to one account

    # Cross-reference with roster.yaml
    if _ROSTER_PATH.exists():
        with open(_ROSTER_PATH) as f:
            roster = yaml.safe_load(f) or {}
        roster_labels = set((roster.get("accounts") or {}).keys())
        env_labels = set(_accounts.keys())
        for lbl in roster_labels - env_labels:
            print(f"WARNING: '{lbl}' in roster.yaml but no keys in .env")
        for lbl in env_labels - roster_labels:
            print(f"WARNING: '{lbl}' has keys in .env but not in roster.yaml")

    if _accounts:
        registered = [l for l, a in _accounts.items() if a.api_key]
        print(f"Loaded {len(_accounts)} account(s): {', '.join(_accounts.keys())}")
        if registered:
            print(f"  Kamibots registered: {', '.join(registered)}")
    else:
        print("WARNING: No accounts loaded. Fill .env with *_OPERATOR_KEY entries.")


_load_accounts()


def _get_account(label: str) -> _Account:
    """Look up account by label. Raises ValueError if not found."""
    if label not in _accounts:
        available = ", ".join(_accounts.keys()) or "(none)"
        raise ValueError(f"Account '{label}' not found. Available: {available}")
    return _accounts[label]


# ---------------------------------------------------------------------------
# Transaction helper
# ---------------------------------------------------------------------------


def _send_tx(
    account: str,
    system_id: str,
    abi: list,
    args: list,
    gas_limit: int | None = None,
) -> dict:
    """Build, sign, send a transaction with the account's operator key."""
    acct = _get_account(account)
    addr = _resolve_system(system_id)
    contract = w3.eth.contract(address=addr, abi=abi)
    fn = contract.functions.executeTyped(*args)

    tx_params = {
        "from": acct.operator_addr,
        "chainId": CHAIN_ID,
        "nonce": w3.eth.get_transaction_count(acct.operator_addr),
        **_GAS_PRICE,
    }
    if gas_limit:
        tx_params["gas"] = gas_limit

    built = fn.build_transaction(tx_params)
    signed = w3.eth.account.sign_transaction(built, private_key=acct.operator_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    return {
        "tx_hash": "0x" + receipt.transactionHash.hex(),
        "status": "success" if receipt.status == 1 else "reverted",
        "block": receipt.blockNumber,
        "gas_used": receipt.gasUsed,
        "account": account,
    }


def _send_tx_retry(
    account: str,
    system_id: str,
    abi: list,
    args: list,
    gas_limit: int | None = None,
    retries: int = 3,
) -> dict:
    """_send_tx with retry on transient RPC errors (e.g. -32000 nonce race)."""
    for attempt in range(retries):
        try:
            return _send_tx(account, system_id, abi, args, gas_limit)
        except Exception as e:
            if attempt < retries - 1 and "-32000" in str(e):
                time.sleep(1)
                continue
            raise


# ---------------------------------------------------------------------------
# Kamibots API helpers
# ---------------------------------------------------------------------------


def _headers(account: str) -> dict:
    acct = _get_account(account)
    if not acct.api_key:
        raise ValueError(
            f"No Kamibots API key for account '{account}'. "
            f"Call register_kamibots(account='{account}') first."
        )
    return {"X-Agent-Key": acct.api_key}


async def _api_get(path: str, account: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{KAMIBOTS_BASE}{path}", headers=_headers(account))
        r.raise_for_status()
        return r.json()


async def _api_post(path: str, body: dict | None, account: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{KAMIBOTS_BASE}{path}", headers=_headers(account), json=body or {}
        )
        r.raise_for_status()
        return r.json()


async def _api_delete(path: str, body: dict | None, account: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(
            "DELETE",
            f"{KAMIBOTS_BASE}{path}",
            headers={**_headers(account), "Content-Type": "application/json"},
            content=json.dumps(body) if body else None,
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("kamigotchi-executor")

# ---- Setup & account management ----


@mcp.tool()
def list_accounts() -> dict:
    """List all configured accounts with labels and public addresses.

    No private data is exposed. Shows whether Kamibots API is registered.
    """
    accts = {}
    for label, acct in _accounts.items():
        accts[label] = {
            "operator_address": acct.operator_addr,
            "owner_address": acct.owner_addr,
            "kamibots_registered": acct.api_key is not None,
        }
    return {"accounts": accts}


@mcp.tool()
async def register_kamibots(account: str = "main") -> dict:
    """Register with Kamibots API using the account's owner wallet.

    Signs a registration message, obtains API key and privy_id, and saves
    them to .env as {LABEL}_KAMIBOTS_API_KEY and {LABEL}_PRIVY_ID.
    Each account gets its own credentials — call once per account.

    Args:
        account: Account label (must have an owner key in .env).
    """
    acct = _get_account(account)
    if not acct.owner_key:
        raise ValueError(
            f"Account '{account}' has no owner key. "
            f"Set {account.upper()}_OWNER_KEY in .env."
        )

    timestamp = int(time.time())
    message = f"Register for Kamibots: {timestamp}"
    signable = encode_defunct(text=message)
    signed = w3.eth.account.sign_message(signable, private_key=acct.owner_key)

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{KAMIBOTS_BASE}/api/agent/register",
            json={
                "walletAddress": acct.owner_addr,
                "signature": "0x" + signed.signature.hex(),
                "message": message,
                "label": f"Agent ({account})",
            },
        )
        r.raise_for_status()
        data = r.json()

    up = account.upper()
    api_key = data.get("apiKey")
    privy_id = data.get("privyId")

    if api_key:
        acct.api_key = api_key
        set_key(str(_KEYS_PATH), f"{up}_KAMIBOTS_API_KEY", api_key)
    if privy_id:
        acct.privy_id = privy_id
        set_key(str(_KEYS_PATH), f"{up}_PRIVY_ID", privy_id)

    return {
        "registered": True,
        "is_new_user": data.get("isNewUser"),
        "has_operator_key": data.get("hasOperatorKey"),
        "api_key_saved": bool(api_key),
        "privy_id_saved": bool(privy_id),
        "message": f"Credentials saved as {up}_KAMIBOTS_API_KEY and {up}_PRIVY_ID. "
        f"Next: call store_operator_key(account='{account}').",
    }


@mcp.tool()
async def store_operator_key(account: str = "main") -> dict:
    """Send the account's operator key to Kamibots for strategy execution.

    The key is encrypted at rest (AES-256-GCM) on Kamibots servers.
    Must be called after register_kamibots() and before starting strategies.

    Args:
        account: Account label.
    """
    acct = _get_account(account)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{KAMIBOTS_BASE}/api/agent/operator-key",
            headers=_headers(account),
            json={"operatorKey": acct.operator_key},
        )
        r.raise_for_status()

    return {
        "account": account,
        "operator_address": acct.operator_addr,
        "stored": True,
        "message": "Operator key stored securely",
    }


# ---- Kamibots API: state reads ----


@mcp.tool()
async def get_tier(account: str = "main") -> dict:
    """Account tier info: tier name, tax rate, total/used/remaining strategy slots.

    Args:
        account: Account label.
    """
    return await _api_get("/api/agent/tier", account)


@mcp.tool()
async def get_inventory(account: str = "main") -> dict:
    """All items and balances in the account inventory.

    Args:
        account: Account label.
    """
    return await _api_get("/api/agent/inventory?compact=true", account)


@mcp.tool()
async def get_kami_state(kami_id: int, account: str = "main") -> dict:
    """Full kami data via playwright endpoint: stats, harvest, skills, traits, bonuses.

    Args:
        kami_id: Kami token index (e.g. 45).
        account: Account label (for context).
    """
    return await _api_get(f"/api/playwright/kami/{kami_id}/", account)


@mcp.tool()
async def get_kami_state_slim(kami_id: int, account: str = "main") -> dict:
    """Slim kami data: stats, harvest, skills, bonuses. Lighter than full state.

    Args:
        kami_id: Kami token index (e.g. 45).
        account: Account label (for context).
    """
    return await _api_get(f"/api/playwright/kami/{kami_id}/slim", account)


@mcp.tool()
async def get_all_strategies(account: str = "main") -> dict:
    """List all active strategies for this account.

    Args:
        account: Account label.
    """
    return await _api_get("/api/agent/strategies", account)


@mcp.tool()
async def get_guild_members(account: str = "main") -> dict:
    """List all guild and team member account names.

    Useful for building a dynamic friendly list (e.g. bodyguard
    friendAccountNames) so guild members don't attack each other.
    Restricted to GUILD and TEAM tier accounts.

    Args:
        account: Account label.
    """
    return await _api_get("/api/agent/guild/members", account)


@mcp.tool()
async def get_strategy_status(kami_id: int, account: str = "main") -> dict:
    """Strategy status for a specific kami. Cached 15s server-side.

    Args:
        kami_id: Kami token index.
        account: Account label (for context).
    """
    return await _api_get(f"/api/strategies/status/{kami_id}", account)


@mcp.tool()
async def get_strategy_logs(
    container_id: str, tail: int = 30, account: str = "main"
) -> dict:
    """Recent log lines from a running strategy container.

    Args:
        container_id: Strategy container ID (from start response or strategy list).
        tail: Number of log lines to return (default 30).
        account: Account label (for context).
    """
    return await _api_get(f"/api/strategies/{container_id}/logs?tail={tail}", account)


@mcp.tool()
async def get_prices(account: str = "main") -> dict:
    """Latest marketplace prices for all items. Cached ~3 minutes.

    Args:
        account: Account label (any registered account works).
    """
    return await _api_get("/api/prices/latest", account)


@mcp.tool()
async def get_npc_prices(account: str = "main") -> dict:
    """Live NPC shop prices for all items.

    Args:
        account: Account label (any registered account works).
    """
    return await _api_get("/api/npc-prices/live", account)


@mcp.tool()
async def get_nodes(account: str = "main") -> dict:
    """All harvest nodes: affinity, room, drops, level requirements. Cached 24h.

    Args:
        account: Account label (any registered account works).
    """
    return await _api_get("/api/playwright/nodes", account)


@mcp.tool()
async def get_account_kamis(
    account: str = "main", address: str = ""
) -> dict:
    """List all kamis for an address. Defaults to the account's operator address.

    Args:
        account: Account label.
        address: Override address (default: account's operator address).
    """
    if not address:
        address = _get_account(account).operator_addr
    return await _api_get(f"/api/accounts/{address}/kamis", account)


# ---- Kamibots API: strategy management ----


@mcp.tool()
async def start_strategy(
    strategy_type: str,
    kami_id: int,
    node_id: int,
    config: dict,
    account: str = "main",
) -> dict:
    """Start a Kamibots strategy for a kami.

    Args:
        strategy_type: One of harvestAndRest, harvestAndFeed, rest_v3,
            auto_v2, bodyguard, craft.
        kami_id: Kami token index (e.g. 45). For craft strategies, pass 0.
        node_id: Harvest node index. Must match kami's current room.
        config: Strategy-specific config dict.
            See integration/kamibots/README.md for schemas.
        account: Account label.
    """
    acct = _get_account(account)
    if not acct.privy_id:
        raise ValueError(
            f"No privy_id for account '{account}'. "
            f"Call register_kamibots(account='{account}') first."
        )
    return await _api_post(
        "/api/strategies/start",
        {
            "strategyType": strategy_type,
            "kamiId": kami_id,
            "nodeId": node_id,
            "config": config,
            "keyData": {"privy_id": acct.privy_id},
        },
        account,
    )


@mcp.tool()
async def stop_strategy(kami_id: str, account: str = "main") -> dict:
    """Stop the running strategy for a kami.

    Args:
        kami_id: Kami token index (e.g. "45") or craft strategy ID (e.g. "craft_zpki5vkc").
        account: Account label.
    """
    acct = _get_account(account)
    if not acct.privy_id:
        raise ValueError(
            f"No privy_id for account '{account}'. "
            f"Call register_kamibots(account='{account}') first."
        )
    return await _api_delete(
        f"/api/strategies/kami/{kami_id}",
        {"keyData": {"privy_id": acct.privy_id}},
        account,
    )


# ---- On-chain: direct game actions ----

_ABI_MOVE = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"roomIndex","type":"uint32"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)
_ABI_FEED = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"kamiID","type":"uint256"},{"name":"itemIndex","type":"uint32"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)
_ABI_REVIVE = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"id","type":"uint256"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)
_ABI_LEVEL = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"kamiID","type":"uint256"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)
_ABI_SKILL = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"holderID","type":"uint256"},{"name":"skillIndex","type":"uint32"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)
_ABI_EQUIP = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"kamiID","type":"uint256"},{"name":"itemIndex","type":"uint32"}],'
    '"outputs":[{"type":"uint256"}],"stateMutability":"nonpayable"}]'
)
_ABI_UNEQUIP = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"kamiID","type":"uint256"},{"name":"slotType","type":"string"}],'
    '"outputs":[{"type":"uint32"}],"stateMutability":"nonpayable"}]'
)


@mcp.tool()
def move_to_room(room_index: int, account: str = "main") -> dict:
    """Move the account to a different room. Costs stamina.

    Args:
        room_index: Target room number (1-70). See catalogs/rooms.csv.
        account: Account label.
    """
    return _send_tx(
        account, "system.account.move", _ABI_MOVE, [room_index], gas_limit=1_200_000
    )


@mcp.tool()
def feed_kami(kami_id: int, food_item_id: int, account: str = "main") -> dict:
    """Use a food item on a kami to restore HP. Works while harvesting.

    Args:
        kami_id: Kami token index (e.g. 45).
        food_item_id: Item ID for the food. Common foods:
            11301=gum(25hp), 11302=burger(50hp), 11303=candy(50hp),
            11304=cookies(100hp), 11311=resin(35hp), 11312=honeydew(75hp),
            11313=golden_apple(150hp), 11314=blue_pansy(25hp).
        account: Account label.
    """
    return _send_tx(
        account,
        "system.kami.use.item",
        _ABI_FEED,
        [_kami_entity_id(kami_id), food_item_id],
    )


@mcp.tool()
def revive_kami(kami_id: int, account: str = "main") -> dict:
    """Revive a dead kami. Costs 33 Onyx Shards. Restores 33 HP -> RESTING.

    Args:
        kami_id: Kami token index (e.g. 45).
        account: Account label.
    """
    return _send_tx(account, "system.kami.onyx.revive", _ABI_REVIVE, [kami_id])


@mcp.tool()
def level_up_kami(kami_id: int, account: str = "main") -> dict:
    """Level up a kami if it has enough XP. Grants 1 skill point.

    Args:
        kami_id: Kami token index (e.g. 45).
        account: Account label.
    """
    return _send_tx(
        account, "system.kami.level", _ABI_LEVEL, [_kami_entity_id(kami_id)]
    )


@mcp.tool()
def upgrade_skill(kami_id: int, skill_index: int, account: str = "main") -> dict:
    """Upgrade a skill on a kami by 1 point. Costs 1 SP. Kami must be RESTING.

    Args:
        kami_id: Kami token index (e.g. 45).
        skill_index: Skill index from catalogs/skills.csv (e.g. 311 for
            Guardian Defensiveness, 212 for Enlightened Cardio).
        account: Account label.
    """
    return _send_tx(
        account,
        "system.skill.upgrade",
        _ABI_SKILL,
        [_kami_entity_id(kami_id), skill_index],
    )


@mcp.tool()
def allocate_skills(
    kami_id: int, skill_plan: list[dict], account: str = "main"
) -> dict:
    """Allocate multiple skill points in one call. Executes sequentially on-chain.

    Args:
        kami_id: Kami token index.
        skill_plan: List of {"skill_index": int, "points": int} dicts.
            Example: [{"skill_index": 311, "points": 5}, {"skill_index": 312, "points": 5}]
            Must respect tier gate ordering — lower tiers first.
        account: Account label.
    """
    entity_id = _kami_entity_id(kami_id)
    total_planned = sum(s["points"] for s in skill_plan)
    done = 0
    for skill in skill_plan:
        for _ in range(skill["points"]):
            try:
                _send_tx_retry(
                    account, "system.skill.upgrade", _ABI_SKILL,
                    [entity_id, skill["skill_index"]],
                )
                done += 1
            except Exception as e:
                return {
                    "kami_id": kami_id,
                    "allocated": done,
                    "failed_at": skill["skill_index"],
                    "total_planned": total_planned,
                    "error": str(e),
                }
    return {
        "kami_id": kami_id,
        "allocated": done,
        "total_planned": total_planned,
        "success": True,
    }


@mcp.tool()
async def level_to(
    kami_id: int, target_level: int, account: str = "main"
) -> dict:
    """Level up a kami repeatedly until it reaches target_level.

    Queries current level from the API, then executes the exact number of
    level-up transactions needed. Retries on transient RPC errors.

    Args:
        kami_id: Kami token index (e.g. 45).
        target_level: Desired level (e.g. 32). Must have enough XP banked.
        account: Account label.
    """
    state = await _api_get(f"/api/playwright/kami/{kami_id}/", account)
    current = state["progress"]["level"]
    levels_needed = target_level - current
    if levels_needed <= 0:
        return {
            "kami_id": kami_id,
            "current_level": current,
            "target_level": target_level,
            "message": "Already at or above target level",
        }
    entity_id = _kami_entity_id(kami_id)
    done = 0
    for _ in range(levels_needed):
        try:
            r = _send_tx_retry(
                account, "system.kami.level", _ABI_LEVEL, [entity_id],
            )
            if r["status"] != "success":
                break
            done += 1
        except Exception as e:
            return {
                "kami_id": kami_id,
                "from_level": current,
                "reached_level": current + done,
                "target_level": target_level,
                "levels_gained": done,
                "error": str(e),
            }
    return {
        "kami_id": kami_id,
        "from_level": current,
        "reached_level": current + done,
        "target_level": target_level,
        "levels_gained": done,
        "success": current + done >= target_level,
    }


@mcp.tool()
def use_item_batch(
    kami_id: int, item_id: int, count: int, account: str = "main"
) -> dict:
    """Use the same item on a kami multiple times. Executes sequentially.

    Works for any consumable: food (HP), XP potions, buff potions, etc.
    Retries on transient RPC errors.

    Args:
        kami_id: Kami token index (e.g. 45).
        item_id: Item ID (e.g. 11411 for Fortified XP Potion, 11302 for Burger).
        count: Number of times to use the item.
        account: Account label.
    """
    entity_id = _kami_entity_id(kami_id)
    done = 0
    for _ in range(count):
        try:
            _send_tx_retry(
                account, "system.kami.use.item", _ABI_FEED,
                [entity_id, item_id],
            )
            done += 1
        except Exception as e:
            return {
                "kami_id": kami_id,
                "item_id": item_id,
                "used": done,
                "planned": count,
                "error": str(e),
            }
    return {
        "kami_id": kami_id,
        "item_id": item_id,
        "used": done,
        "planned": count,
        "success": True,
    }


@mcp.tool()
def equip_item(kami_id: int, item_index: int, account: str = "main") -> dict:
    """Equip an inventory item to a kami. Kami must be RESTING.

    Args:
        kami_id: Kami token index (e.g. 45).
        item_index: Item index from inventory (e.g. 1001 for Wooden Stick).
        account: Account label.
    """
    return _send_tx(
        account,
        "system.kami.equip",
        _ABI_EQUIP,
        [_kami_entity_id(kami_id), item_index],
    )


@mcp.tool()
def unequip_item(kami_id: int, slot_type: str, account: str = "main") -> dict:
    """Unequip an item from a kami slot. Kami must be RESTING.

    Args:
        kami_id: Kami token index (e.g. 45).
        slot_type: Equipment slot name (e.g. "Kami_Pet_Slot").
        account: Account label.
    """
    return _send_tx(
        account,
        "system.kami.unequip",
        _ABI_UNEQUIP,
        [_kami_entity_id(kami_id), slot_type],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
