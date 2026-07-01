# OpenShift + OpenShell Cluster Deployment

> **Status:** Full watcher + OpenShell pipeline validated on OpenShift 4.21.
> Watcher polls Jira, dispatches agents in OpenShell sandboxes on cluster.
> Infrastructure E2E verified (Qwen 3.6 via LiteMaaS — investigation runs,
> implementation needs stronger model). Local OpenShell sandbox E2E verified
> with Claude Opus (investigate + implement + PR creation).
>
> See the Troubleshooting section at the bottom of this guide for common issues.

## 1. Build and Push Image

```bash
# Always build for linux/amd64 (even from Apple Silicon)
podman build --no-cache --platform linux/amd64 \
  -t quay.io/rzalavad/issue-fix-agent:latest -f Containerfile .
podman push quay.io/rzalavad/issue-fix-agent:latest
```

Image includes: Python 3.11, OpenCode, OpenShell CLI, gh CLI, git,
Go, ripgrep, curl, jq, atlassian-python-api, python-dotenv.

## 2. Install OpenShell on Cluster

```bash
# Agent Sandbox CRD
oc apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/latest/download/manifest.yaml

# OpenShell gateway via Helm
oc create namespace openshell
helm upgrade --install openshell \
  oci://ghcr.io/nvidia/openshell/helm-chart \
  --version 0.0.62 \
  --namespace openshell \
  --set server.auth.allowUnauthenticatedUsers=true

# Grant SCCs (required for Landlock/seccomp)
oc adm policy add-scc-to-user anyuid -z openshell -n openshell
oc adm policy add-scc-to-user anyuid -z default -n openshell
oc adm policy add-scc-to-user privileged -z openshell-sandbox -n openshell

# Verify gateway
oc get pods -n openshell                 # should show openshell-0 Running
```

> **Note**: `allowUnauthenticatedUsers=true` is for dev/testing.
> For production, configure OIDC or ServiceAccount token auth.

## 3. Deploy Watcher

```bash
# Namespace, RBAC, storage
oc apply -f manifests/namespace.yaml
oc apply -f manifests/rbac.yaml
oc apply -f manifests/pvc.yaml

# Secrets (replace with your values — do NOT use secrets.yaml template)
oc create secret generic watcher-secrets \
  --from-literal=GITHUB_TOKEN="$GITHUB_TOKEN" \
  --from-literal=JIRA_USERNAME="$JIRA_USERNAME" \
  --from-literal=JIRA_API_TOKEN="$JIRA_API_TOKEN" \
  -n issue-fix-agent

oc create secret generic litemaas-config \
  --from-literal=opencode.json='<your LiteMaaS opencode.json>' \
  -n issue-fix-agent

# Config (review configmap.yaml — start with DRY_RUN=true)
oc apply -f manifests/configmap.yaml

# Copy OpenShell TLS certs to watcher namespace
oc get secret openshell-client-tls -n openshell -o json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  d['metadata']={'name':'openshell-client-tls','namespace':'issue-fix-agent'}; \
  print(json.dumps(d))" | oc apply -n issue-fix-agent -f -

# Deploy
oc apply -f manifests/deployment.yaml

# Verify
oc logs deploy/issue-fix-watcher -n issue-fix-agent
# Should show: "Watcher starting in loop mode"
```

## 4. Verify and Go Live

```bash
# Check DRY_RUN mode works (should show Jira polling without mutations)
oc logs -f deploy/issue-fix-watcher -n issue-fix-agent

# Switch to live mode (edit configmap: DRY_RUN=false)
oc apply -f manifests/configmap.yaml
oc rollout restart deploy/issue-fix-watcher -n issue-fix-agent

# Apply network hardening
oc apply -f manifests/networkpolicy.yaml
oc apply -f manifests/resourcequota.yaml
```

## Deploy Order (Important)

```
1. OpenShell (gateway must exist before watcher starts — TLS secret dependency)
2. Namespace + RBAC + PVC
3. Secrets (watcher-secrets + litemaas-config)
4. ConfigMap (start with DRY_RUN=true)
5. Copy TLS secret from openshell → issue-fix-agent namespace
6. Deployment
7. Verify → switch DRY_RUN=false
8. NetworkPolicy + ResourceQuota
```

## Configuration Flags

Key flags in the configmap (`manifests/configmap.yaml`):

| Flag | Default | Description |
|------|---------|-------------|
| `DRY_RUN` | `false` | Start with `true` to verify Jira polling without mutations |
| `FORK_MODE` | `false` | `true`: auto-fork upstream repos, cross-repo PRs. `false`: push directly |
| `PLAN_IN_PR` | `true` | `true`: plan file in PR. `false`: plan in Jira comment only |
| `DEPLOY_MODE` | auto | Auto-detected (`openshift+openshell`). Override if needed |
| `SANDBOX_ENABLED` | `true` | Enable OpenShell sandbox for agent dispatch |

## Cluster Model Note

The configmap defaults to `litemaas/Qwen3.6-35B-A3B` (the only model
available on cluster via LiteMaaS). Per eval results:
- **Investigation**: works (4/6 correct root cause identification)
- **Implementation**: fails (0/6 — instruction following insufficient)

For full E2E on cluster, configure Vertex AI with a GCP service account,
or wait for a stronger open model on LiteMaaS.

## Credentials

| Credential | Where | Stored as |
|------------|-------|-----------|
| GitHub token | Local: `$GITHUB_TOKEN` env var | Cluster: K8s Secret `watcher-secrets` |
| Jira API token | Local: `$JIRA_API_TOKEN` env var | Cluster: K8s Secret `watcher-secrets` |
| LiteMaaS API key | Local: `.opencode/opencode.json` | Cluster: K8s Secret `litemaas-config` |

## Troubleshooting

Common issues encountered during deployment:
- SCC permission failures
- OpenShell sandbox pod stuck in Pending
- Image pull errors
- TLS certificate issues
- LiteMaaS connectivity from cluster
