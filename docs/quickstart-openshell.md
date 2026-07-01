# Quick Start — OpenShell Sandbox (Local)

Run agents inside an OpenShell sandbox for production-like isolation
(Landlock filesystem, seccomp syscall filtering, network policy enforcement).
Works on macOS via Docker Desktop / Podman.

## 1. Prerequisites

```bash
# OpenShell CLI
openshell --version                      # v0.0.71+

# Container runtime (Podman or Docker Desktop)
podman machine list                      # or: docker info

# Local OpenShell gateway
openshell status                         # should show "Connected"

# If gateway not running:
openshell gateway add http://127.0.0.1:17670 --local
```

If `openshell sandbox create` fails with "network not found" (Podman only):
```bash
podman network create openshell-docker   # one-time setup, not needed for Docker Desktop
```

## 2. Sandbox Policy

The repo includes pre-configured restrictive policies in `policies/`:

- `fix-investigate.yaml` — for investigation agent
- `fix-implement.yaml` — for implementation agent
- `review.yaml` / `review-fix.yaml` — for review agents

Each policy enforces:
- **Filesystem**: Landlock-restricted (read-only `/usr`, `/lib`, `/etc`; write only `/sandbox`, `/tmp`)
- **Network**: Only allowed endpoints (GitHub, Jira, Vertex AI, LiteMaaS) — all other outbound blocked

For **local Ollama** models, add the Ollama endpoint to the policy:

```yaml
# Append to network_policies section in policies/fix-investigate.yaml:
  ollama:
    endpoints:
      - host: host.docker.internal
        port: 11434
        protocol: rest
        access: full
    binaries:
      - path: /**
```

For **Vertex AI**, the policy already includes `us-east5-aiplatform.googleapis.com`.
You must also add `oauth2.googleapis.com` for Application Default Credentials
(required for token refresh):

```yaml
# Append under vertex_ai endpoints in policies/fix-investigate.yaml:
      - host: oauth2.googleapis.com
        port: 443
        protocol: rest
        access: full
```

> **Note:** Uploaded gcloud credentials land at `~/gcloud/` inside the sandbox
> (HOME=/sandbox). The Vertex AI example command creates a symlink to
> `~/.config/gcloud/` for SDK discovery.

## 3. Run in Sandbox

**With Vertex AI (Opus/Sonnet):**

```bash
# Requires gcloud Application Default Credentials
openshell sandbox create --name fix-run \
  --policy policies/fix-investigate.yaml \
  --upload .opencode \
  --upload opencode.json \
  --upload AGENTS.md \
  --upload ~/.config/gcloud \
  --env "JIRA_USERNAME=$JIRA_USERNAME" \
  --env "JIRA_API_TOKEN=$JIRA_API_TOKEN" \
  --env "GITHUB_TOKEN=$GITHUB_TOKEN" \
  --env "JIRA_URL=https://your-jira.atlassian.net" \
  --env "CLAUDE_CODE_USE_VERTEX=1" \
  --env "ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project" \
  --env "GOOGLE_CLOUD_PROJECT=your-gcp-project" \
  --env "CLOUD_ML_REGION=us-east5" \
  --env "GOOGLE_APPLICATION_CREDENTIALS=/sandbox/gcloud/application_default_credentials.json" \
  --no-keep \
  -- bash -c '
    mkdir -p ~/.config && ln -s ~/gcloud ~/.config/gcloud
    opencode run --agent fix-investigate \
      -m google-vertex-anthropic/claude-sonnet-4-6@default \
      "Investigate Jira ticket YOUR-TICKET. Follow the skill."
  '
```

**Configuration flags** — pass via `--env` to control behavior:
- `FORK_MODE=true`: auto-fork upstream, cross-repo PRs (default: `false`)
- `PLAN_IN_PR=false`: plan in Jira comment only, not in PR (default: `true`)

**With Ollama (local models):**

```bash
openshell sandbox create --name fix-run \
  --policy policies/fix-investigate.yaml \
  --upload .opencode \
  --upload opencode.json \
  --upload AGENTS.md \
  --env "JIRA_USERNAME=$JIRA_USERNAME" \
  --env "JIRA_API_TOKEN=$JIRA_API_TOKEN" \
  --env "GITHUB_TOKEN=$GITHUB_TOKEN" \
  --env "JIRA_URL=https://your-jira.atlassian.net" \
  --no-keep \
  -- opencode run --agent fix-investigate \
    -m ollama/deepseek-r1:32b \
    "Investigate Jira ticket YOUR-TICKET. Follow the skill."
```

> **Note:** Open models (DeepSeek, Gemma4) have limited reliability in the
> sandbox — same as local runs. See Model Recommendations in the main README.

> **Note:** The sandbox OpenCode version (v1.2.18) differs from the local
> install (v1.17.11). Core `run` functionality works but some flags like
> `--dangerously-skip-permissions` are not available — the sandbox handles
> permissions via policy instead.

## 4. Key Differences from Local Runs

| Aspect | Local (`opencode run`) | Sandbox (`openshell sandbox create`) |
|--------|----------------------|--------------------------------------|
| Filesystem | Full host access | Landlock-restricted (workdir + /tmp) |
| Network | Unrestricted | Policy-controlled (only allowed hosts) |
| Permissions | `--dangerously-skip-permissions` | Sandbox policy enforces |
| Ollama URL | `localhost:11434` | `host.docker.internal:11434` |
| gcloud creds | `~/.config/gcloud/` auto-discovered | Must upload + set `GOOGLE_APPLICATION_CREDENTIALS` |
| Cleanup | Manual (`rm -rf work/ target-repo/`) | Automatic (`--no-keep`) |
