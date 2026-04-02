#!/usr/bin/env bash
# Bootstrap script for the local MUD sync infrastructure.
# TODO: verify against current MUD indexer docs — package versions
#       and Docker image tags may have changed since this was written.

set -euo pipefail
cd "$(dirname "$0")"

INDEXER_URL="http://localhost:${INDEXER_PORT:-3001}"

# --- Prerequisites ---

check_docker() {
  if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found. Install Docker: https://docs.docker.com/get-docker/"
    exit 1
  fi
  if ! docker compose version &>/dev/null; then
    echo "ERROR: docker compose v2 not found. Update Docker or install compose plugin."
    exit 1
  fi
  echo "✓ Docker and Compose found"
}

# --- Setup ---

setup_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ Created .env from .env.example — edit if needed"
  else
    echo "✓ .env already exists"
  fi
}

# --- Start ---

start_services() {
  echo "Starting PostgreSQL + MUD indexer..."
  docker compose up -d
  echo "✓ Services started"
}

# --- Wait for sync ---

wait_for_health() {
  local max_wait=120
  local elapsed=0
  echo "Waiting for indexer to become healthy (up to ${max_wait}s)..."

  while [ $elapsed -lt $max_wait ]; do
    if curl -sf "${INDEXER_URL}/health" &>/dev/null; then
      echo "✓ Indexer is healthy"
      return 0
    fi
    sleep 3
    elapsed=$((elapsed + 3))
    printf "  %ds...\r" "$elapsed"
  done

  echo "WARNING: Indexer did not become healthy within ${max_wait}s."
  echo "  This may be normal during initial sync of a long chain history."
  echo "  Check logs: docker compose logs -f indexer"
  return 1
}

# --- Smoke test ---

smoke_test() {
  local chain_id="${CHAIN_ID:-428962654539583}"
  local store_addr="${STORE_ADDRESS:-0x2729174c265dbBd8416C6449E0E813E88f43D0E7}"

  echo "Running smoke test against REST API..."
  local input
  input=$(python3 -c "import urllib.parse,json; print(urllib.parse.quote(json.dumps({'chainId':${chain_id},'address':'${store_addr}','filters':[]})))")

  local response
  response=$(curl -sf "${INDEXER_URL}/api/logs?input=${input}" 2>/dev/null) || {
    echo "WARNING: REST API smoke test failed. Indexer may still be syncing."
    echo "  Retry manually: curl '${INDEXER_URL}/api/logs?input=${input}'"
    return 1
  }

  # Check if we got a blockNumber back
  if echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✓ Synced to block {d[\"blockNumber\"]}, {len(d.get(\"logs\",[]))} log entries returned')" 2>/dev/null; then
    return 0
  else
    echo "WARNING: Unexpected response format. Check indexer logs."
    return 1
  fi
}

# --- Main ---

echo "=== Kamigotchi MUD Sync Setup ==="
echo ""
check_docker
setup_env
start_services
echo ""
wait_for_health || true
smoke_test || true
echo ""
echo "=== Setup complete ==="
echo "  Indexer API: ${INDEXER_URL}"
echo "  PostgreSQL:  localhost:${POSTGRES_PORT:-5432}"
echo "  Logs:        docker compose logs -f indexer"
echo "  Query guide: query-examples.md"
