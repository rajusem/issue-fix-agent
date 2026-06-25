# OpenShift Cluster Setup Guide: Issue-Fix Agent

> Last updated: 2026-06-24
> Tested on: OpenShift 4.21 (`p3.openshiftapps.com` managed clusters)
> Full sandbox E2E verified: investigation + implementation agents
> running inside OpenShell sandboxes with Qwen 3.6 35B via LiteMaaS

## Prerequisites

- `oc` CLI logged in as `cluster-admin`
- `helm` CLI installed
- `podman` or `docker` for building images
- Container image pushed to `quay.io/rzalavad/issue-fix-agent:latest`

## Step 1: Build and Push Container Image

```bash
# From the issue-fix-agent repo root
podman build --no-cache --platform linux/amd64 \
  -t quay.io/rzalavad/issue-fix-agent:latest \
  -f Containerfile .

podman push quay.io/rzalavad/issue-fix-agent:latest
```

Image includes: Python 3.11, OpenCode, OpenShell CLI, gh CLI, git,
Go, ripgrep, curl, jq, atlassian-python-api, python-dotenv.

**Important**: The image includes a `sandbox` user (UID 1000) required
by OpenShell when using `--from` with a custom image.

**Note**: Always build with `--platform linux/amd64` from Apple Silicon.

## Step 2: Deploy Watcher (Issue-Fix Agent)

### 2a. Create namespace and RBAC

```bash
oc apply -f manifests/namespace.yaml
oc apply -f manifests/rbac.yaml
```

### 2b. Create PVC

```bash
oc apply -f manifests/pvc.yaml
```

### 2c. Create secrets

**Watcher credentials** (replace with real values):
```bash
oc create secret generic watcher-secrets \
  --from-literal=GITHUB_TOKEN="<your-github-token>" \
  --from-literal=JIRA_USERNAME="<your-jira-email>" \
  --from-literal=JIRA_API_TOKEN="<your-jira-api-token>" \
  -n issue-fix-agent
```

**LiteMaaS config** (OpenCode provider config — replace API key):
```bash
oc create secret generic litemaas-config \
  --from-literal=opencode.json='{
    "$schema": "https://opencode.ai/config.json",
    "provider": {
      "litemaas": {
        "npm": "@ai-sdk/openai-compatible",
        "name": "LiteMaaS",
        "options": {
          "baseURL": "https://litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com/v1",
          "apiKey": "<your-litemaas-key>"
        },
        "models": {
          "Qwen3.6-35B-A3B": {
            "name": "Qwen 3.6 35B (LiteMaaS)",
            "contextWindow": 131072
          }
        }
      }
    }
  }' -n issue-fix-agent
```

### 2d. Create ConfigMap

```bash
oc apply -f manifests/configmap.yaml
```

Key config values to review:
- `JIRA_POLL_INTERVAL=10` — polling frequency (minutes)
- `FIX_MODEL=litemaas/Qwen3.6-35B-A3B` — model for agents
- `DRY_RUN=true` — set `false` for production (start with `true` to verify)
- `AUDIT_ENABLED=false` — audit sub-agents need separate model access
- `SANDBOX_ENABLED=true` — enables OpenShell sandbox isolation (requires Step 3)

### 2e. Deploy watcher

```bash
oc apply -f manifests/deployment.yaml
```

### 2f. Verify

```bash
# Check pod is running
oc get pods -n issue-fix-agent

# Check logs — should show "Watcher starting in loop mode"
oc logs deploy/issue-fix-watcher -n issue-fix-agent

# Verify LiteMaaS is reachable
oc exec deploy/issue-fix-watcher -n issue-fix-agent -- \
  curl -s -o /dev/null -w "LiteMaaS: HTTP %{http_code}\n" \
  https://litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com/health
```

## Step 3: Install OpenShell (Sandbox Isolation)

### 3a. Install Agent Sandbox CRD

```bash
oc apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/latest/download/manifest.yaml
```

### 3b. Install OpenShell gateway via Helm

```bash
oc create namespace openshell

helm upgrade --install openshell \
  oci://ghcr.io/nvidia/openshell/helm-chart \
  --version 0.0.62 \
  --namespace openshell \
  --set server.auth.allowUnauthenticatedUsers=true
```

**Note**: `allowUnauthenticatedUsers=true` is for dev/testing.
For production, configure OIDC or ServiceAccount token auth.

**Verified**: Sandbox creation works with this config. With custom
image (`--from`), sandbox pods pull our image (~1.6 GB) and run
agents with full config access.

### 3c. Grant SCCs

OpenShell gateway needs `anyuid`, sandbox pods need `privileged`:

```bash
# Gateway pod (runs as UID 1000)
oc adm policy add-scc-to-user anyuid -z openshell -n openshell
oc adm policy add-scc-to-user anyuid -z default -n openshell

# Sandbox pods (need root + NET_ADMIN + SYS_ADMIN for Landlock)
oc adm policy add-scc-to-user privileged -z openshell-sandbox -n openshell
```

### 3d. Verify gateway

```bash
# Check gateway pod is running
oc get pods -n openshell

# Check logs
oc logs statefulset/openshell -n openshell | tail -5
# Should show: "Server listening" + "Using compute driver: kubernetes"
```

### 3e. Copy client TLS certs to watcher namespace

```bash
oc get secret openshell-client-tls -n openshell -o json | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
d['metadata'] = {'name': 'openshell-client-tls', 'namespace': 'issue-fix-agent'}
print(json.dumps(d))
" | oc apply -n issue-fix-agent -f -
```

### 3f. Redeploy watcher (picks up TLS mount)

The deployment manifest already includes TLS cert mounts and init
script to register the gateway. Just restart:

```bash
oc rollout restart deploy/issue-fix-watcher -n issue-fix-agent
```

### 3g. Verify sandbox creation

```bash
oc exec deploy/issue-fix-watcher -n issue-fix-agent -- \
  openshell sandbox create --name sandbox-test \
  --from quay.io/rzalavad/issue-fix-agent:latest \
  -- echo "SANDBOX WORKS"
```

Expected: sandbox pod created with custom image, runs echo, exits.

### 3h. Enable sandboxing

Ensure `SANDBOX_ENABLED=true` in `manifests/configmap.yaml`, then:
```bash
oc apply -f manifests/configmap.yaml
oc rollout restart deploy/issue-fix-watcher -n issue-fix-agent
```

**How sandbox dispatch works**: The dispatcher uses `--from` to run
sandboxes with our custom image. An init script inside the sandbox
creates symlinks from `/app/` to `/tmp/` for OpenCode config discovery
and writes the LiteMaaS config from the `LITEMAAS_CONFIG` env var.

## Step 4: Test E2E Pipeline

### 4a. Create test ticket

Create a Jira Bug in your watched project with:
- Labels: `autofix`
- Description with `## Agent Configuration` section containing
  `**Repository**:` and `**Branch**:` fields

### 4b. Monitor watcher

```bash
oc logs deploy/issue-fix-watcher -n issue-fix-agent -f
```

Expected flow:
1. Phase 1: Detects ticket → dispatches `fix-investigate` (in sandbox)
2. Agent investigates → posts plan → swaps to `bot-plan-ready`
3. Human adds `bot-plan-approved` (or `bot-proceed`) label
4. Phase 1B: Detects approval → dispatches `fix-implement` (in sandbox)
5. Agent implements → creates PR → swaps to `bot-ready-for-review`
6. Phase 2: Detects PR → dispatches `review` agent
7. Review passes → `bot-review-complete` → human merges

### 4c. Check agent logs

```bash
oc exec deploy/issue-fix-watcher -n issue-fix-agent -- \
  ls /app/orchestrator/logs/

oc exec deploy/issue-fix-watcher -n issue-fix-agent -- \
  tail -20 /app/orchestrator/logs/<ticket>-fix-investigate-*.log
```

## Troubleshooting

### Pod won't start — SCC errors

```bash
oc get events -n issue-fix-agent --sort-by='.lastTimestamp' | tail -5
```

Common fix: ensure deployment has correct securityContext:
```yaml
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
containers:
  - securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
```

### Agent dispatched but dies immediately

Check agent log for errors:
```bash
oc exec deploy/issue-fix-watcher -n issue-fix-agent -- \
  cat /app/orchestrator/logs/<ticket>-*.log | head -5
```

Common issues:
- `ripgrep execution failed` → ripgrep not in image
- `ProviderModelNotFoundError` → LiteMaaS config not mounted at `/tmp/.opencode/`
- `PermissionDenied: FileSystem.open` → OpenCode dirs not writable
- `Exec format error` → image built for wrong architecture

### Sandbox agent fails

Check watcher-side log:
```bash
oc exec deploy/issue-fix-watcher -n issue-fix-agent -- \
  bash -c 'ls -t /app/orchestrator/logs/* | head -1 | xargs tail -20'
```

Common sandbox issues:
- `sandbox user 'sandbox' not found` → add `sandbox` user to Containerfile
- `Forbidden: policy_denied` → widen `binaries` path in policies to `/**`
- `ProviderModelNotFoundError` inside sandbox → LiteMaaS config not injected via env var
- `/dev/null: Permission denied` → add `/dev` to policy `read_write`
- `ssh exited with status 1` + opencode help text → wrong opencode version; use `--from` with custom image

### LiteMaaS not reachable

```bash
oc run net-test --rm -i --restart=Never --image=curlimages/curl -- \
  curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  https://litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com/health
```

Expected: HTTP 401 (auth required = network works).

### OpenShell sandbox fails

Check sandbox pod events:
```bash
oc get events -n openshell --sort-by='.lastTimestamp' | tail -10
```

Common issues:
- SCC rejection → grant privileged SCC to `openshell-sandbox` SA
- Image pull → sandbox base image may need pull secret
- mTLS errors → ensure client TLS secret is copied and mounted

## Quick Reference

| Resource | Namespace | Purpose |
|----------|-----------|---------|
| Deployment `issue-fix-watcher` | `issue-fix-agent` | Watcher + agent dispatch |
| Secret `watcher-secrets` | `issue-fix-agent` | GitHub + Jira credentials |
| Secret `litemaas-config` | `issue-fix-agent` | LiteMaaS provider config |
| Secret `openshell-client-tls` | `issue-fix-agent` | OpenShell gateway mTLS certs |
| ConfigMap `watcher-config` | `issue-fix-agent` | config.env + projects.json |
| PVC `watcher-data` | `issue-fix-agent` | State, logs, runs (20Gi) |
| StatefulSet `openshell` | `openshell` | OpenShell gateway |
| CRD `sandboxes.agents.x-k8s.io` | cluster-wide | Agent Sandbox CRD |

## Credentials Needed

| Credential | Where to get | Stored as |
|------------|-------------|-----------|
| GitHub token | `gh auth token` or GitHub Settings | K8s Secret |
| Jira API token | [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) | K8s Secret |
| LiteMaaS API key | LiteMaaS admin (rh-aiservices-bu team) | K8s Secret (in opencode.json) |

## Step 5: Production Hardening

### 5a. Apply NetworkPolicy

Restricts watcher egress to Jira, GitHub, LiteMaaS, OpenShell, DNS:
```bash
oc apply -f manifests/networkpolicy.yaml
```

Sandbox pod egress is separately controlled by OpenShell Landlock
policies in `policies/*.yaml`.

### 5b. Apply ResourceQuota

```bash
oc apply -f manifests/resourcequota.yaml
```

Caps: 20 pods, 16 CPU requests, 32Gi memory requests.

### 5c. For production Jira

Replace the stage hostname in sandbox policies:
```bash
JIRA_HOST=your-production.atlassian.net
sed -i "s/stage-redhat.atlassian.net/$JIRA_HOST/g" policies/*.yaml
```

Also update `JIRA_SITE` in `manifests/configmap.yaml` and rebuild
the image.

## Step 6: Post-Deploy (Required for Sandbox Reliability)

### 6a. Grant admin RBAC to sandbox controller

The agent-sandbox-controller needs broader permissions than its
default manifest provides:
```bash
oc create clusterrolebinding sandbox-controller-admin \
  --clusterrole=admin \
  --serviceaccount=agent-sandbox-system:agent-sandbox-controller
```

### 6b. Verify sandbox creation

```bash
oc exec deploy/issue-fix-watcher -n issue-fix-agent -- \
  openshell sandbox create --name test \
  --from quay.io/rzalavad/issue-fix-agent:latest \
  -- echo "SANDBOX WORKS"
```

If this fails with "supervisor session not connected", wait 30s
and retry — the supervisor has a startup race condition. The
dispatcher retries automatically (3 attempts, 15s delay).

## Issues Found During Setup (40 total)

See `local-docs/learnings.md` for the full list of issues discovered
during iterative cluster deployment testing:
- Issues 1-22: basic pipeline
- Issues 23-29: OpenShell sandbox integration
- Issues 30-32: credential injection into sandboxes
- Issues 33-40: production hardening + Go toolchain + sandbox reliability
