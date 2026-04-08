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

import csv
import json
import os
import struct
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
    '"outputs":[{"type":"address"}],"stateMutability":"view"},'
    '{"type":"function","name":"components","inputs":[],'
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


def _harvest_entity_id(kami_entity_id: int) -> int:
    """Derive harvest entity ID: keccak256("harvest", kamiEntityId)."""
    return int.from_bytes(
        Web3.solidity_keccak(["string", "uint256"], ["harvest", kami_entity_id]), "big"
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


def _send_tx_owner(
    account: str,
    system_id: str,
    abi: list,
    args: list,
    gas_limit: int | None = None,
) -> dict:
    """Build, sign, send a transaction with the account's owner key."""
    acct = _get_account(account)
    if not acct.owner_key:
        raise ValueError(
            f"Account '{account}' has no owner key. "
            f"Set {account.upper()}_OWNER_KEY in .env."
        )
    addr = _resolve_system(system_id)
    contract = w3.eth.contract(address=addr, abi=abi)
    fn = contract.functions.executeTyped(*args)

    tx_params = {
        "from": acct.owner_addr,
        "chainId": CHAIN_ID,
        "nonce": w3.eth.get_transaction_count(acct.owner_addr),
        **_GAS_PRICE,
    }
    if gas_limit:
        tx_params["gas"] = gas_limit

    built = fn.build_transaction(tx_params)
    signed = w3.eth.account.sign_transaction(built, private_key=acct.owner_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    return {
        "tx_hash": "0x" + receipt.transactionHash.hex(),
        "status": "success" if receipt.status == 1 else "reverted",
        "block": receipt.blockNumber,
        "gas_used": receipt.gasUsed,
        "account": account,
    }


# ---------------------------------------------------------------------------
# Component resolution (for on-chain reads)
# ---------------------------------------------------------------------------

_component_cache: dict[str, str] = {}


def _resolve_component(component_id: str) -> str:
    """Resolve component ID to on-chain contract address (cached).

    Components resolve via world.components(), NOT world.systems().
    """
    if component_id not in _component_cache:
        h = int.from_bytes(Web3.keccak(text=component_id), "big")
        cc_addr = _world.functions.components().call()
        cc = w3.eth.contract(address=cc_addr, abi=_SYSTEMS_COMPONENT_ABI)
        entities = cc.functions.getEntitiesWithValue(h).call()
        if not entities:
            raise ValueError(f"Component not found on-chain: {component_id}")
        addr = Web3.to_checksum_address(
            "0x" + hex(entities[0])[2:].zfill(40)[-40:]
        )
        _component_cache[component_id] = addr
    return _component_cache[component_id]


_ID_COMPONENT_ABI = json.loads(
    '[{"type":"function","name":"getEntitiesWithValue",'
    '"inputs":[{"name":"v","type":"uint256"}],'
    '"outputs":[{"type":"uint256[]"}],"stateMutability":"view"},'
    '{"type":"function","name":"getValue",'
    '"inputs":[{"name":"entity","type":"uint256"}],'
    '"outputs":[{"type":"uint256"}],"stateMutability":"view"},'
    '{"type":"function","name":"has",'
    '"inputs":[{"name":"entity","type":"uint256"}],'
    '"outputs":[{"type":"bool"}],"stateMutability":"view"}]'
)

_STATE_COMPONENT_ABI = json.loads(
    '[{"type":"function","name":"getValue",'
    '"inputs":[{"name":"entity","type":"uint256"}],'
    '"outputs":[{"type":"string"}],"stateMutability":"view"}]'
)

_BOOL_COMPONENT_ABI = json.loads(
    '[{"type":"function","name":"has",'
    '"inputs":[{"name":"entity","type":"uint256"}],'
    '"outputs":[{"type":"bool"}],"stateMutability":"view"}]'
)


# ---------------------------------------------------------------------------
# Item name lookup (from catalogs/items.csv)
# ---------------------------------------------------------------------------

_ITEM_NAMES: dict[int, str] = {}


def _get_item_name(index: int) -> str:
    """Return human-readable item name for an item index."""
    if not _ITEM_NAMES:
        csv_path = _REPO / "catalogs" / "items.csv"
        if csv_path.exists():
            with open(csv_path) as f:
                for row in csv.DictReader(f):
                    _ITEM_NAMES[int(row["Index"])] = row["Name"]
    return _ITEM_NAMES.get(index, f"Unknown({index})")


# ---------------------------------------------------------------------------
# Kamiden gRPC-Web helpers (trade data from the indexer)
# ---------------------------------------------------------------------------

_KAMIDEN_URL = "https://api.prod.kamigotchi.io"


def _proto_encode_varint(value: int) -> bytes:
    r = []
    while value > 127:
        r.append((value & 0x7F) | 0x80)
        value >>= 7
    r.append(value)
    return bytes(r)


def _proto_encode_string_field(field_num: int, value: str) -> bytes:
    tag = _proto_encode_varint((field_num << 3) | 2)
    data = value.encode("utf-8")
    return tag + _proto_encode_varint(len(data)) + data


def _proto_encode_varint_field(field_num: int, value: int) -> bytes:
    return _proto_encode_varint((field_num << 3) | 0) + _proto_encode_varint(
        value
    )


def _proto_read_varint(data: bytes, offset: int):
    result, shift = 0, 0
    while offset < len(data):
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, offset
        shift += 7
    return None, offset


def _proto_decode_fields(data: bytes) -> dict:
    """Decode a flat protobuf message into {field_num: [(kind, value), ...]}."""
    fields: dict = {}
    offset = 0
    while offset < len(data):
        tag, offset = _proto_read_varint(data, offset)
        if tag is None:
            break
        field_num, wire_type = tag >> 3, tag & 0x07
        if wire_type == 0:
            val, offset = _proto_read_varint(data, offset)
            fields.setdefault(field_num, []).append(("varint", val))
        elif wire_type == 2:
            length, offset = _proto_read_varint(data, offset)
            if length is None or offset + length > len(data):
                break
            val = data[offset : offset + length]
            offset += length
            fields.setdefault(field_num, []).append(("bytes", val))
        elif wire_type == 1:
            val = data[offset : offset + 8]
            offset += 8
            fields.setdefault(field_num, []).append(("fixed64", val))
        elif wire_type == 5:
            val = data[offset : offset + 4]
            offset += 4
            fields.setdefault(field_num, []).append(("fixed32", val))
        else:
            break
    return fields


def _proto_field_str(fields: dict, num: int) -> str:
    if num in fields:
        _, raw = fields[num][0]
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
    return ""


def _proto_field_bytes(fields: dict, num: int) -> bytes:
    if num in fields:
        _, raw = fields[num][0]
        if isinstance(raw, bytes):
            return raw
    return b""


def _kamiden_grpc_call(method: str, body: bytes = b"") -> bytes:
    """Make a gRPC-Web unary call to Kamiden and return the data payload."""
    frame = b"\x00" + struct.pack(">I", len(body)) + body
    resp = httpx.post(
        f"{_KAMIDEN_URL}/{method}",
        content=frame,
        headers={
            "Content-Type": "application/grpc-web+proto",
            "Accept": "application/grpc-web+proto",
            "X-Grpc-Web": "1",
        },
        timeout=30,
    )
    data = resp.content
    off = 0
    while off < len(data):
        if off + 5 > len(data):
            break
        ft = data[off]
        fl = struct.unpack(">I", data[off + 1 : off + 5])[0]
        payload = data[off + 5 : off + 5 + fl]
        if ft == 0 and len(payload) > 0:
            return payload
        off += 5 + fl
    return b""


def _parse_kamiden_trades(payload: bytes) -> list[dict]:
    """Parse a Kamiden TradesResponse into a list of trade dicts.

    Proto field mapping (reverse-engineered from Kamiden):
      f1 = trade entity ID (decimal string)
      f2 = maker account entity ID (decimal string)
      f3 = counterparty entity ID (decimal string)
      f4 = direction (bytes: 0x01 = buying items with MUSU)
      f5 = MUSU amount (string)
      f6 = item index (varint encoded in bytes field)
      f7 = item quantity (string)
      f8 = created_at unix timestamp (string)
      f10 = executed_at unix timestamp (string)
      f11 = completed_at unix timestamp (string)
    """
    trades = []
    outer = _proto_decode_fields(payload)
    for _, raw in outer.get(1, []):
        if not isinstance(raw, bytes):
            continue
        f = _proto_decode_fields(raw)
        # Decode item index from varint-encoded bytes in field 6
        item_raw = _proto_field_bytes(f, 6)
        if item_raw:
            item_index, _ = _proto_read_varint(item_raw, 0)
            item_index = item_index or 0
        else:
            item_index = 0

        direction_raw = _proto_field_bytes(f, 4)
        direction_val = (
            int.from_bytes(direction_raw, "big") if direction_raw else 0
        )

        trade_entity_id = _proto_field_str(f, 1)
        musu_amount = _proto_field_str(f, 5)
        item_amount = _proto_field_str(f, 7)
        executed_at = _proto_field_str(f, 10)
        completed_at = _proto_field_str(f, 11)

        # Determine status from timestamps
        if completed_at and completed_at != "0":
            status = "COMPLETED"
        elif executed_at and executed_at != "0":
            status = "EXECUTED"
        else:
            status = "PENDING"

        trade_id_hex = hex(int(trade_entity_id)) if trade_entity_id else "0x0"
        item_name = _get_item_name(item_index)
        musu_int = int(musu_amount) if musu_amount else 0
        qty_int = int(item_amount) if item_amount else 0

        # Build human-readable summary
        if direction_val == 1:
            side = "BUY"
            summary = f"Buying {qty_int:,}x {item_name} for {musu_int:,} MUSU"
        else:
            side = "SELL"
            summary = f"Selling {qty_int:,}x {item_name} for {musu_int:,} MUSU"
        if qty_int > 0 and musu_int > 0:
            summary += f" ({musu_int / qty_int:.0f} MUSU/ea)"

        trades.append(
            {
                "trade_id_hex": trade_id_hex,
                "status": status,
                "side": side,
                "item_index": item_index,
                "item_name": item_name,
                "item_amount": qty_int,
                "musu_amount": musu_int,
                "unit_price": round(musu_int / qty_int) if qty_int > 0 else 0,
                "summary": summary,
                "created_at": _proto_field_str(f, 8) or None,
                "executed_at": executed_at or None,
                "completed_at": completed_at or None,
            }
        )
    return trades


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
async def get_killer_ranking(account: str = "main") -> dict:
    """Top predator kamis ranked by kill count. Cached 1h.

    Use this to identify the strongest predators in the game.
    Cross-reference with get_kami_state to check their affinity,
    violence, attack bonuses, and equipment.

    Args:
        account: Account label (any registered account works).
    """
    return await _api_get("/api/killer-ranking", account)


@mcp.tool()
async def get_leaderboard(leaderboard_type: str, account: str = "main") -> dict:
    """Game leaderboards. Cached 20m.

    Args:
        leaderboard_type: One of 'harvest' or 'kill'.
        account: Account label (any registered account works).
    """
    return await _api_get(f"/api/leaderboards/{leaderboard_type}", account)


@mcp.tool()
async def get_all_kamis(account: str = "main") -> dict:
    """All kamis in the game with stats, affinities, bonuses. Cached 24h.

    Returns every kami's violence, harmony, power, health, affinity (body/hand),
    level, state, and bonuses. Use for predator threat modeling:
    filter by high violence + attack bonuses to find dangerous predators,
    then cross-reference affinity against your kamis' body type.

    Args:
        account: Account label (any registered account works).
    """
    return await _api_get("/api/playwright/kamis/all", account)


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
    failed = 0
    for skill in skill_plan:
        for _ in range(skill["points"]):
            try:
                _send_tx_retry(
                    account, "system.skill.upgrade", _ABI_SKILL,
                    [entity_id, skill["skill_index"]],
                )
                done += 1
            except Exception as e:
                failed += 1
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


# ---- On-chain: marketplace ----

_ABI_LIST_KAMI = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"kamiIndex","type":"uint32"},'
    '{"name":"price","type":"uint256"},'
    '{"name":"expiry","type":"uint256"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)


@mcp.tool()
def list_kami(
    kami_id: int, price_eth: str, expiry: int = 0, account: str = "main"
) -> dict:
    """List a Kami for sale on KamiSwap. Kami must be RESTING and not soulbound.

    The Kami stays in your wallet but enters LISTED state (can't harvest/move).
    Uses the operator wallet.

    Args:
        kami_id: Kami token index (e.g. 45).
        price_eth: Listing price as a decimal string in ETH (e.g. "0.1").
        expiry: Expiration unix timestamp. 0 = no expiration.
        account: Account label.
    """
    price_wei = int(float(price_eth) * 10**18)
    if price_wei <= 0:
        raise ValueError("Price must be > 0")
    return _send_tx(
        account,
        "system.kamimarket.list",
        _ABI_LIST_KAMI,
        [kami_id, price_wei, expiry],
    )


# ---- On-chain: trading ----

_ABI_TRADE_CREATE = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"buyIndices","type":"uint32[]"},'
    '{"name":"buyAmts","type":"uint256[]"},'
    '{"name":"sellIndices","type":"uint32[]"},'
    '{"name":"sellAmts","type":"uint256[]"},'
    '{"name":"targetID","type":"uint256"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)

_ABI_TRADE_CANCEL = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"tradeID","type":"uint256"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)

_ABI_TRADE_COMPLETE = json.loads(
    '[{"type":"function","name":"executeTyped",'
    '"inputs":[{"name":"tradeID","type":"uint256"}],'
    '"outputs":[{"type":"bytes"}],"stateMutability":"nonpayable"}]'
)


@mcp.tool()
def get_account_trades(account: str = "main") -> dict:
    """Show open and recently executed trades for this account.

    Returns item names, quantities, MUSU amounts, unit prices, and status
    for every active trade listing. Uses the Kamiden indexer for rich data
    and on-chain dry-runs to detect EXECUTED trades ready for completion.

    Args:
        account: Account label.
    """
    acct = _get_account(account)
    account_entity_id = str(int(acct.owner_addr, 16))

    # --- Fetch open offers from Kamiden indexer (no auth required) ---
    req = _proto_encode_string_field(
        1, account_entity_id
    ) + _proto_encode_varint_field(2, 500)

    try:
        payload = _kamiden_grpc_call(
            "kamiden.KamidenService/GetOpenOffers", req
        )
        open_trades = _parse_kamiden_trades(payload) if payload else []
    except Exception as e:
        open_trades = []
        indexer_error = str(e)
    else:
        indexer_error = None

    # --- Check which open trades are actually EXECUTED (taker accepted) ---
    # Dry-run complete() on-chain for each trade to detect EXECUTED status.
    executed_ids: set[str] = set()
    if acct.owner_key and open_trades:
        try:
            complete_sys = w3.eth.contract(
                address=_resolve_system("system.trade.complete"),
                abi=_ABI_TRADE_COMPLETE,
            )
            for t in open_trades:
                try:
                    te = int(t["trade_id_hex"], 16)
                    complete_sys.functions.executeTyped(te).call(
                        {"from": acct.owner_addr}
                    )
                    executed_ids.add(t["trade_id_hex"])
                except Exception:
                    pass
        except Exception:
            pass  # Can't resolve system — skip status check

    # Also check trade history for EXECUTED-but-not-completed trades
    executed_trades = []
    try:
        hist_payload = _kamiden_grpc_call(
            "kamiden.KamidenService/GetTradeHistory", req
        )
        if hist_payload:
            history = _parse_kamiden_trades(hist_payload)
            for t in history:
                if t["status"] == "EXECUTED":
                    executed_trades.append(t)
                    executed_ids.add(t["trade_id_hex"])
    except Exception:
        pass

    # --- Update statuses and build result ---
    pending = []
    executed = []
    for t in open_trades:
        if t["trade_id_hex"] in executed_ids:
            t["status"] = "EXECUTED"
            t["action"] = "complete_trade"
            executed.append(t)
        else:
            t["status"] = "PENDING"
            t["action"] = "cancel_trade"
            pending.append(t)

    # Add any EXECUTED trades found only in history
    open_ids = {t["trade_id_hex"] for t in open_trades}
    for t in executed_trades:
        if t["trade_id_hex"] not in open_ids:
            t["action"] = "complete_trade"
            executed.append(t)

    # --- Summarize by price tier for readability ---
    price_summary: dict[str, dict] = {}
    for t in pending:
        key = f"{t['item_name']}@{t['unit_price']}"
        if key not in price_summary:
            price_summary[key] = {
                "item_name": t["item_name"],
                "item_index": t["item_index"],
                "side": t["side"],
                "unit_price": t["unit_price"],
                "total_qty": 0,
                "total_musu": 0,
                "count": 0,
            }
        price_summary[key]["total_qty"] += t["item_amount"]
        price_summary[key]["total_musu"] += t["musu_amount"]
        price_summary[key]["count"] += 1

    result: dict = {
        "account": account,
        "pending": len(pending),
        "executed": len(executed),
        "total_open": len(pending) + len(executed),
    }

    if indexer_error:
        result["indexer_error"] = indexer_error

    if price_summary:
        result["pending_summary"] = sorted(
            price_summary.values(), key=lambda x: x["unit_price"]
        )

    if executed:
        result["executed_trades"] = [
            {
                "trade_id_hex": t["trade_id_hex"],
                "summary": t["summary"],
                "action": "complete_trade",
            }
            for t in executed
        ]

    result["trades"] = [
        {
            "trade_id_hex": t["trade_id_hex"],
            "status": t["status"],
            "action": t.get("action"),
            "summary": t["summary"],
            "item_name": t["item_name"],
            "item_index": t["item_index"],
            "item_amount": t["item_amount"],
            "musu_amount": t["musu_amount"],
            "unit_price": t["unit_price"],
            "side": t["side"],
        }
        for t in pending + executed
    ]

    return result


@mcp.tool()
def complete_trade(trade_id: str, account: str = "main") -> dict:
    """Complete an executed trade. Called by the maker (owner wallet).

    The trade must be in EXECUTED status (taker already accepted).
    Items are distributed to both parties.

    Args:
        trade_id: Trade entity ID (decimal or hex string starting with 0x).
        account: Account label.
    """
    trade_int = int(trade_id, 16) if trade_id.startswith("0x") else int(trade_id)
    return _send_tx_owner(
        account, "system.trade.complete", _ABI_TRADE_COMPLETE, [trade_int]
    )


@mcp.tool()
def complete_all_trades(account: str = "main") -> dict:
    """Find and complete all EXECUTED trades for this account.

    Discovers trades via on-chain components, filters for EXECUTED status,
    and completes each one. Only trades where this account is the maker
    can be completed.

    Args:
        account: Account label.
    """
    discovery = get_account_trades(account)
    trades = discovery.get("trades", [])

    executed = [t for t in trades if t.get("status") == "EXECUTED"]
    if not executed:
        return {
            "account": account,
            "total_found": len(trades),
            "executed_found": 0,
            "message": "No EXECUTED trades to complete",
        }

    results = []
    for t in executed:
        trade_int = int(t["trade_id_hex"], 16)
        try:
            r = _send_tx_owner(
                account, "system.trade.complete", _ABI_TRADE_COMPLETE,
                [trade_int],
            )
            results.append({
                "trade_id": t["trade_id_hex"],
                **r,
            })
        except Exception as e:
            results.append({
                "trade_id": t["trade_id_hex"],
                "status": "error",
                "error": str(e),
            })

    succeeded = sum(1 for r in results if r.get("status") == "success")
    return {
        "account": account,
        "total_found": len(trades),
        "executed_found": len(executed),
        "completed": succeeded,
        "failed": len(executed) - succeeded,
        "results": results,
    }


@mcp.tool()
def create_trade(
    sell_item: int,
    sell_amount: int,
    buy_item: int,
    buy_amount: int,
    account: str = "main",
) -> dict:
    """Create a trade offer on the in-game marketplace. Uses owner wallet.

    One side must be MUSU (item index 1). Sell items are escrowed immediately.
    The trade is open to anyone (no target restriction).

    Common patterns:
      Sell items for MUSU: sell_item=<item>, buy_item=1, buy_amount=<musu>
      Buy items with MUSU: sell_item=1, sell_amount=<musu>, buy_item=<item>

    Args:
        sell_item: Item index you are offering (e.g. 1 for MUSU, 11312 for Honeydew).
        sell_amount: Quantity to offer.
        buy_item: Item index you want in return.
        buy_amount: Quantity you want.
        account: Account label.
    """
    if sell_item != 1 and buy_item != 1:
        raise ValueError(
            "One side of the trade must be MUSU (item index 1). "
            "Direct item-for-item barter is not supported."
        )
    return _send_tx_owner(
        account,
        "system.trade.create",
        _ABI_TRADE_CREATE,
        [[buy_item], [buy_amount], [sell_item], [sell_amount], 0],
    )


@mcp.tool()
def cancel_trade(trade_id: str, account: str = "main") -> dict:
    """Cancel a pending trade. Returns escrowed items to inventory. Owner wallet.

    Only the maker can cancel, and only while the trade is in PENDING status.

    Args:
        trade_id: Trade entity ID (decimal or hex string starting with 0x).
        account: Account label.
    """
    trade_int = int(trade_id, 16) if trade_id.startswith("0x") else int(trade_id)
    return _send_tx_owner(
        account, "system.trade.cancel", _ABI_TRADE_CANCEL, [trade_int]
    )


# ---- On-chain: batch harvest stop ----

_ABI_HARVEST_STOP_BATCH = json.loads(
    '[{"type":"function","name":"executeBatchedAllowFailure",'
    '"inputs":[{"name":"ids","type":"uint256[]"}],'
    '"outputs":[{"type":"bytes[]"}],"stateMutability":"nonpayable"}]'
)


@mcp.tool()
def stop_harvest_batch(
    kami_ids: list[int], account: str = "main"
) -> dict:
    """Stop harvests for multiple kamis in one transaction. Collects rewards automatically.

    Uses executeBatchedAllowFailure — skips kamis that aren't harvesting
    instead of reverting the entire batch. Max ~10 per batch recommended.

    Args:
        kami_ids: List of kami token indices (e.g. [45, 46, 47]).
        account: Account label.
    """
    harvest_ids = [
        _harvest_entity_id(_kami_entity_id(kid)) for kid in kami_ids
    ]

    acct = _get_account(account)
    addr = _resolve_system("system.harvest.stop")
    contract = w3.eth.contract(address=addr, abi=_ABI_HARVEST_STOP_BATCH)
    fn = contract.functions.executeBatchedAllowFailure(harvest_ids)

    tx_params = {
        "from": acct.operator_addr,
        "chainId": CHAIN_ID,
        "nonce": w3.eth.get_transaction_count(acct.operator_addr),
        **_GAS_PRICE,
    }

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
        "kami_ids": kami_ids,
        "count": len(kami_ids),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
