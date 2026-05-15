#!/usr/bin/env bash
# ===========================================================================
# Minerva Local Dev – Seed Script
#
# Initializes Vault with test SSH credentials and registers a test node
# via the Minerva API. Run after `docker compose up` is fully healthy.
#
# Prerequisites:
#   - All services running (db, redis, vault, backend, test-node)
#   - `curl` and `jq` available on the host
#
# Usage:
#   chmod +x dev/seed-local.sh
#   ./dev/seed-local.sh
# ===========================================================================
set -uo pipefail
# NOTE: -e is intentionally omitted; individual steps handle their own errors

API_URL="${API_URL:-http://localhost:8000/api/v1}"
VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-minerva-dev-token}"

# Temporary cookie jar for JWT (auth is cookie-based, not bearer token in body)
COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT

echo "=== Minerva Local Dev Seed ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Enable Vault KV v2 (dev mode already mounts 'secret/' as KV v1 by default;
#    we upgrade to v2 or skip if already v2)
# ---------------------------------------------------------------------------
echo "[1/5] Configuring Vault KV v2 engine..."

# Try to tune the existing 'secret/' mount to v2; ignore errors (already v2 or dev mode)
MOUNT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${VAULT_ADDR}/v1/sys/mounts/secret/tune" \
  -H "X-Vault-Token: ${VAULT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"options":{"version":"2"}}')

if [ "$MOUNT_STATUS" = "200" ]; then
  echo "  → secret/ mount tuned to KV v2"
else
  echo "  → secret/ mount already configured (HTTP ${MOUNT_STATUS}) — OK"
fi

# ---------------------------------------------------------------------------
# 2. Write test SSH password credential to Vault (KV v2 path: secret/data/...)
# ---------------------------------------------------------------------------
echo "[2/5] Writing test SSH credential to Vault..."
WRITE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${VAULT_ADDR}/v1/secret/data/ansible/test-node" \
  -H "X-Vault-Token: ${VAULT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"data":{"password":"testpassword","username":"testuser"}}')

if [ "$WRITE_STATUS" = "200" ] || [ "$WRITE_STATUS" = "204" ]; then
  echo "  → Vault: secret/ansible/test-node written"
else
  echo "  ✗ Vault write failed (HTTP ${WRITE_STATUS}). Is Vault running?"
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. Register admin user
# ---------------------------------------------------------------------------
echo "[3/5] Registering admin user..."

REG_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -c "$COOKIE_JAR" \
  -X POST "${API_URL}/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@example.com","password":"admin1234"}')

case "$REG_STATUS" in
  201) echo "  → Admin user created" ;;
  400) echo "  → Admin user already exists (OK)" ;;
  *)   echo "  ✗ Register failed (HTTP ${REG_STATUS}). Check backend logs."; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# 4. Login (JWT is set as httpOnly cookie, not returned in body)
# ---------------------------------------------------------------------------
echo "[4/5] Logging in..."

LOGIN_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -c "$COOKIE_JAR" \
  -X POST "${API_URL}/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin1234"}')

if [ "$LOGIN_STATUS" != "200" ]; then
  echo "  ✗ Login failed (HTTP ${LOGIN_STATUS}). Check backend logs."
  exit 1
fi
echo "  → Logged in (session cookie saved)"

# Verify we're actually authenticated
ME=$(curl -s -b "$COOKIE_JAR" "${API_URL}/auth/me")
ME_USERNAME=$(echo "$ME" | jq -r '.username // empty' 2>/dev/null)
if [ -z "$ME_USERNAME" ]; then
  echo "  ✗ Could not verify login. Response: ${ME}"
  exit 1
fi
echo "  → Authenticated as: ${ME_USERNAME}"

# ---------------------------------------------------------------------------
# 5. Create credential (vault metadata) + register test node
# ---------------------------------------------------------------------------
echo "[5/5] Creating SSH credential and registering test node..."

# Create credential
CRED_RESP=$(curl -s -b "$COOKIE_JAR" \
  -X POST "${API_URL}/credentials" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-node-ssh",
    "type": "ssh_password",
    "vault_path": "ansible/test-node",
    "secret": {"password": "testpassword", "username": "testuser"}
  }')

CRED_ID=$(echo "$CRED_RESP" | jq -r '.id // empty' 2>/dev/null)

if [ -z "$CRED_ID" ]; then
  # 409 = already exists; fetch existing
  CRED_ID=$(curl -s -b "$COOKIE_JAR" "${API_URL}/credentials" \
    | jq -r '.[0].id // empty' 2>/dev/null)
  if [ -z "$CRED_ID" ]; then
    echo "  ✗ Could not create or fetch credential. Response: ${CRED_RESP}"
    exit 1
  fi
  echo "  → Using existing credential ID: ${CRED_ID}"
else
  echo "  → Credential created. ID: ${CRED_ID}"
fi

# Register test node
# host = 'test-node' (Docker service name; resolvable inside the Docker network
#   by celery-worker/backend). From host, SSH is accessible at localhost:2222.
NODE_RESP=$(curl -s -b "$COOKIE_JAR" \
  -X POST "${API_URL}/nodes" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"test-node-01\",
    \"host\": \"test-node\",
    \"port\": 22,
    \"ssh_user\": \"testuser\",
    \"credential_id\": \"${CRED_ID}\",
    \"tags\": [\"dev\", \"test\"]
  }")

NODE_ID=$(echo "$NODE_RESP" | jq -r '.id // empty' 2>/dev/null)

if [ -z "$NODE_ID" ]; then
  echo "  → Node may already exist or creation failed. Response: ${NODE_RESP}"
else
  echo "  → Node registered. ID: ${NODE_ID}"
fi

echo ""
echo "=== Seed Complete ==="
echo ""
echo "  Swagger API: http://localhost:8000/docs"
echo "  Vault UI:    http://localhost:8200  (Token: ${VAULT_TOKEN})"
echo "  Web UI:      http://localhost:8888"
echo ""
echo "  Test SSH:    ssh testuser@localhost -p 2222"
echo "               password: testpassword"
echo ""
echo "  Admin login: username=admin  password=admin1234"
echo ""
