#!/usr/bin/env bash
# Test OpenShell sandbox policies locally.
# Usage: ./scripts/local-sandbox-test.sh [agent-name]
# Example: ./scripts/local-sandbox-test.sh fix-investigate

set -euo pipefail

AGENT="${1:-fix-investigate}"
POLICY="policies/${AGENT}.yaml"

if [ ! -f "$POLICY" ]; then
    echo "ERROR: Policy not found: $POLICY"
    echo "Available policies:"
    ls policies/*.yaml 2>/dev/null || echo "  (none)"
    exit 1
fi

if ! command -v openshell &>/dev/null; then
    echo "ERROR: openshell not found in PATH"
    echo "Install: OPENSHELL_VERSION=v0.0.62 curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh"
    exit 1
fi

echo "Testing sandbox for agent: ${AGENT}"
echo "Policy: ${POLICY}"
echo "---"

openshell sandbox create \
  --name "test-${AGENT}-$(date +%s)" \
  --policy "$POLICY" \
  --cpu 2 --memory 8Gi \
  -- bash -c '
    echo "Sandbox OK"
    echo "Workspace: $(pwd)"
    echo "User: $(whoami)"
    echo "Network test:"
    curl -s -o /dev/null -w "  github.com: %{http_code}\n" https://github.com 2>/dev/null || echo "  github.com: BLOCKED"
    curl -s -o /dev/null -w "  google.com: %{http_code}\n" https://google.com 2>/dev/null || echo "  google.com: BLOCKED (expected)"
    echo "Filesystem:"
    touch /sandbox/test-write && echo "  /sandbox: writable" && rm /sandbox/test-write
    touch /etc/test-write 2>/dev/null && echo "  /etc: writable (BAD)" || echo "  /etc: read-only (expected)"
  '
