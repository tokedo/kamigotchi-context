"""
Kamigotchi MCP Executor — the agent's muscle.

Reads private keys from .env on startup. Exposes game actions as MCP tools.
The LLM (brain) calls tools through Claude Code; this server (muscle) handles
secrets, API auth, and transaction signing. The LLM never sees private keys.

Architecture:
  Claude Code (brain) --MCP--> executor (muscle) ---> Kamibots API / Yominet RPC
"""

import json
import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from web3 import Web3

load_dotenv()

# ---------------------------------------------------------------------------
# Config — all secrets loaded from .env, never exposed to the LLM
# ---------------------------------------------------------------------------

KAMIBOTS_API_KEY: str = os.environ["KAMIBOTS_API_KEY"]
PRIVY_ID: str = os.environ["PRIVY_ID"]
OPERATOR_KEY: str = os.environ["OPERATOR_PRIVATE_KEY"]
RPC_URL: str = os.environ.get(
    "RPC_URL", "https://jsonrpc-yominet-1.anvil.asia-southeast.initia.xyz"
)

KAMIBOTS_BASE = "https://api.kamibots.xyz"
WORLD_ADDRESS = Web3.to_checksum_address(
    "0x2729174c265dbBd8416C6449E0E813E88f43D0E7"
)
CHAIN_ID = 428962654539583

# ---------------------------------------------------------------------------
# Web3 setup
# ---------------------------------------------------------------------------

w3 = Web3(Web3.HTTPProvider(RPC_URL))
_operator_acct = w3.eth.account.from_key(OPERATOR_KEY)
OPERATOR_ADDR = _operator_acct.address

# Yominet flat gas: 0.0025 gwei
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
        addr = Web3.to_checksum_address("0x" + hex(entities[0])[2:].zfill(40)[-40:])
        _system_cache[system_id] = addr
    return _system_cache[system_id]


def _kami_entity_id(kami_index: int) -> int:
    """Derive kami entity ID from token index: keccak256("kami.id", index)."""
    return int.from_bytes(
        Web3.solidity_keccak(["string", "uint32"], ["kami.id", kami_index]), "big"
    )


def _send_tx(
    system_id: str, abi: list, args: list, gas_limit: int | None = None
) -> dict:
    """Build, sign, send a transaction. Returns receipt summary."""
    addr = _resolve_system(system_id)
    contract = w3.eth.contract(address=addr, abi=abi)
    fn = contract.functions.executeTyped(*args)

    tx_params = {
        "from": OPERATOR_ADDR,
        "chainId": CHAIN_ID,
        "nonce": w3.eth.get_transaction_count(OPERATOR_ADDR),
        **_GAS_PRICE,
    }
    if gas_limit:
        tx_params["gas"] = gas_limit

    built = fn.build_transaction(tx_params)
    signed = w3.eth.account.sign_transaction(built, private_key=OPERATOR_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    return {
        "tx_hash": "0x" + receipt.transactionHash.hex(),
        "status": "success" if receipt.status == 1 else "reverted",
        "block": receipt.blockNumber,
        "gas_used": receipt.gasUsed,
    }


# ---------------------------------------------------------------------------
# Kamibots API helpers
# ---------------------------------------------------------------------------


def _headers() -> dict:
    return {"X-Agent-Key": KAMIBOTS_API_KEY}


async def _api_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{KAMIBOTS_BASE}{path}", headers=_headers())
        r.raise_for_status()
        return r.json()


async def _api_post(path: str, body: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{KAMIBOTS_BASE}{path}", headers=_headers(), json=body or {})
        r.raise_for_status()
        return r.json()


async def _api_delete(path: str, body: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(
            "DELETE",
            f"{KAMIBOTS_BASE}{path}",
            headers={**_headers(), "Content-Type": "application/json"},
            content=json.dumps(body) if body else None,
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("kamigotchi-executor")

# ---- Kamibots API: state reads ----


@mcp.tool()
async def get_tier() -> dict:
    """Account tier info: tier name, tax rate, total/used/remaining strategy slots."""
    return await _api_get("/api/agent/tier")


@mcp.tool()
async def get_inventory() -> dict:
    """All items and balances in the account inventory."""
    return await _api_get("/api/agent/inventory")


@mcp.tool()
async def get_kami_state(kami_id: int) -> dict:
    """Full kami data via playwright endpoint: stats, harvest, skills, traits, bonuses.

    Args:
        kami_id: Kami token index (e.g. 45).
    """
    return await _api_get(f"/api/playwright/kami/{kami_id}/")


@mcp.tool()
async def get_kami_state_slim(kami_id: int) -> dict:
    """Slim kami data: stats, harvest, skills, bonuses. Lighter than full state.

    Args:
        kami_id: Kami token index (e.g. 45).
    """
    return await _api_get(f"/api/playwright/kami/{kami_id}/slim")


@mcp.tool()
async def get_all_strategies() -> dict:
    """List all active strategies for this account."""
    return await _api_get("/api/agent/strategies")


@mcp.tool()
async def get_strategy_status(kami_id: int) -> dict:
    """Strategy status for a specific kami. Cached 15s server-side.

    Args:
        kami_id: Kami token index.
    """
    return await _api_get(f"/api/strategies/status/{kami_id}")


@mcp.tool()
async def get_strategy_logs(container_id: str, tail: int = 30) -> dict:
    """Recent log lines from a running strategy container.

    Args:
        container_id: Strategy container ID (from start_strategy response or strategy list).
        tail: Number of log lines to return (default 30).
    """
    return await _api_get(f"/api/strategies/{container_id}/logs?tail={tail}")


@mcp.tool()
async def get_prices() -> dict:
    """Latest marketplace prices for all items. Cached ~3 minutes."""
    return await _api_get("/api/prices/latest")


@mcp.tool()
async def get_npc_prices() -> dict:
    """Live NPC shop prices for all items."""
    return await _api_get("/api/npc-prices/live")


@mcp.tool()
async def get_nodes() -> dict:
    """All harvest nodes: affinity, room, drops, level requirements. Cached 24h."""
    return await _api_get("/api/playwright/nodes")


@mcp.tool()
async def get_account_kamis(address: str) -> dict:
    """List all kamis for an operator address.

    Args:
        address: Operator wallet address (0x...).
    """
    return await _api_get(f"/api/accounts/{address}/kamis")


# ---- Kamibots API: strategy management ----


@mcp.tool()
async def start_strategy(
    strategy_type: str,
    kami_id: int,
    node_id: int,
    config: dict,
) -> dict:
    """Start a Kamibots strategy for a kami.

    Args:
        strategy_type: One of harvestAndRest, harvestAndFeed, rest_v3, auto_v2, bodyguard, craft.
        kami_id: Kami token index (e.g. 45). For craft strategies, pass 0.
        node_id: Harvest node index. Must match kami's current room.
        config: Strategy-specific config. See integration/kamibots/README.md for schemas.
    """
    return await _api_post(
        "/api/strategies/start",
        {
            "strategyType": strategy_type,
            "kamiId": kami_id,
            "nodeId": node_id,
            "config": config,
            "keyData": {"privy_id": PRIVY_ID},
        },
    )


@mcp.tool()
async def stop_strategy(kami_id: int) -> dict:
    """Stop the running strategy for a kami.

    Args:
        kami_id: Kami token index.
    """
    return await _api_delete(
        f"/api/strategies/kami/{kami_id}",
        {"keyData": {"privy_id": PRIVY_ID}},
    )


# ---- On-chain: direct game actions (signed with operator key) ----

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
def move_to_room(room_index: int) -> dict:
    """Move the account to a different room. Costs stamina.

    Args:
        room_index: Target room number (1-70). See catalogs/rooms.csv for the map.
    """
    return _send_tx(
        "system.account.move", _ABI_MOVE, [room_index], gas_limit=1_200_000
    )


@mcp.tool()
def feed_kami(kami_id: int, food_item_id: int) -> dict:
    """Use a food item on a kami to restore HP. Works while harvesting.

    Args:
        kami_id: Kami token index (e.g. 45).
        food_item_id: Item ID for the food. Common foods:
            11301=gum(25hp), 11302=burger(50hp), 11303=candy(50hp),
            11304=cookies(100hp), 11311=resin(35hp), 11312=honeydew(75hp),
            11313=golden_apple(150hp), 11314=blue_pansy(25hp).
    """
    return _send_tx(
        "system.kami.use.item", _ABI_FEED, [_kami_entity_id(kami_id), food_item_id]
    )


@mcp.tool()
def revive_kami(kami_id: int) -> dict:
    """Revive a dead kami. Costs 33 Onyx Shards. Restores 33 HP, state -> RESTING.

    Args:
        kami_id: Kami token index (e.g. 45).
    """
    # Revive takes the token index directly, not entity ID
    return _send_tx("system.kami.onyx.revive", _ABI_REVIVE, [kami_id])


@mcp.tool()
def level_up_kami(kami_id: int) -> dict:
    """Level up a kami if it has enough XP. Grants 1 skill point.

    Args:
        kami_id: Kami token index (e.g. 45).
    """
    return _send_tx("system.kami.level", _ABI_LEVEL, [_kami_entity_id(kami_id)])


@mcp.tool()
def equip_item(kami_id: int, item_index: int) -> dict:
    """Equip an inventory item to a kami. Kami must be RESTING.

    Args:
        kami_id: Kami token index (e.g. 45).
        item_index: Item index from inventory (e.g. 1001 for Wooden Stick).
    """
    return _send_tx(
        "system.kami.equip", _ABI_EQUIP, [_kami_entity_id(kami_id), item_index]
    )


@mcp.tool()
def unequip_item(kami_id: int, slot_type: str) -> dict:
    """Unequip an item from a kami slot. Kami must be RESTING.

    Args:
        kami_id: Kami token index (e.g. 45).
        slot_type: Equipment slot name (e.g. "Kami_Pet_Slot").
    """
    return _send_tx(
        "system.kami.unequip", _ABI_UNEQUIP, [_kami_entity_id(kami_id), slot_type]
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
