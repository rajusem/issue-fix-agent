# Model Configuration Guide

## Quick Reference

| Provider | Model ID | Pass Rate | Best For |
|----------|----------|-----------|----------|
| Vertex AI | `google-vertex-anthropic/claude-sonnet-4-6@default` | 100% (6/6) | All agents (recommended default) |
| Vertex AI | `google-vertex-anthropic/claude-opus-4-6@default` | 100% (6/6) | Complex/high-priority (premium) |
| Ollama | `ollama/deepseek-r1:32b` | 33% (2/6) | Local dev, simple bugs |
| Ollama Cloud | `ollama/minimax-m2.5:cloud` | 40% (2/5) | Simple bugs |
| LiteMaaS | `litemaas/Qwen3.6-35B-A3B` | 0% full, 67% investigate | Cluster, investigation only |

> **Note on pass rates:** "Full" = complete pipeline (investigate → implement → PR).
> "Investigate" = investigation phase only (plan posted, but implementation fails).
> See [eval/README.md](../eval/README.md) for the full 7-model × 6-issue matrix.

## Model ID Format

Format: `<provider>/<model-name>@<variant>`

- `@default` — uses the default model configuration (standard context,
  no custom parameters). Required suffix for Vertex AI models.
- The `@default` variant is the only one currently used.

Examples:
- `google-vertex-anthropic/claude-sonnet-4-6@default`
- `ollama/deepseek-r1:32b` (Ollama models don't use @variant)
- `litemaas/Qwen3.6-35B-A3B` (LiteMaaS models don't use @variant)

## Provider Setup

### Vertex AI (Recommended)

Vertex AI models are configured via environment variables, NOT in
opencode.json.

**Prerequisites:**
- GCP project with Vertex AI API enabled
- IAM: `aiplatform.endpoints.predict` permission (or Vertex AI User role)
- Claude models enabled in your project's Model Garden

**Auth Option 1: Application Default Credentials (local dev)**

```bash
gcloud auth application-default login
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project
export CLOUD_ML_REGION=us-east5
```

**Auth Option 2: Service Account (cluster/sandbox)**

```bash
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project
export GOOGLE_CLOUD_PROJECT=your-gcp-project
export CLOUD_ML_REGION=us-east5
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

For GCP service account creation: create a SA with `Vertex AI User` role,
generate a JSON key, and set `GOOGLE_APPLICATION_CREDENTIALS` to its path.
For K8s deployment, mount the key as a Secret.

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `CLAUDE_CODE_USE_VERTEX` | Yes | Set to `1` to enable Vertex AI |
| `ANTHROPIC_VERTEX_PROJECT_ID` | Yes | GCP project ID |
| `GOOGLE_CLOUD_PROJECT` | Sandbox/cluster | GCP project (for ADC token refresh) |
| `CLOUD_ML_REGION` | Yes | Vertex AI region (e.g., `us-east5`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Sandbox/cluster | Path to SA key JSON |

**Available Models:**

- `google-vertex-anthropic/claude-sonnet-4-6@default` — recommended default
- `google-vertex-anthropic/claude-opus-4-6@default` — premium tier

**Verify:**

```bash
opencode run -m google-vertex-anthropic/claude-sonnet-4-6@default "echo hello"
```

### Ollama (Local Models)

Ollama models are configured in `opencode.json` (committed to repo).

**Install:**

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

**Start and pull models:**

```bash
ollama serve &
ollama pull deepseek-r1:32b    # Recommended local model
ollama pull gemma4:31b          # Alternative (slower)
```

**Configure in opencode.json:**

Models are already configured in the project's `opencode.json` under
`provider.ollama`. Each model entry specifies:
- `baseURL`: Ollama API endpoint (default: `http://localhost:11434/v1`)
- `contextWindow`: Max context in tokens

**Available Models:**

| Model | Context | GPU Memory | Notes |
|-------|---------|------------|-------|
| `deepseek-r1:32b` | 131K | ~20GB | Best local option, 33% pass rate |
| `minimax-m2.5:cloud` | 200K | Cloud-hosted | 40% pass rate, needs Ollama Cloud account |
| `gemma4:31b` | 128K | ~20GB | Slow inference, testing only |
| `qwen3-coder-fixed` | 32K | ~18GB | Context too small, not viable |

**Ollama Cloud (MiniMax M2.5):**

MiniMax M2.5 runs on Ollama's cloud infrastructure, not locally.
Requires an Ollama Cloud account. The model ID `minimax-m2.5:cloud`
routes through the local Ollama server which proxies to the cloud.

**Context Window Requirement:**

Agent mode needs sufficient context for system prompt + skill file +
conversation. Minimum empirical requirement: 32K tokens. Recommended:
100K+ for full pipeline with 3 audit iterations.

**Verify:**

```bash
opencode run -m ollama/deepseek-r1:32b "echo hello"
```

### LiteMaaS (Cluster Models)

LiteMaaS is Red Hat's internal model serving platform. Config lives in
`.opencode/opencode.json` (gitignored — contains API key).

> **Security:** Never commit API keys to source control. The
> `.opencode/opencode.json` file is gitignored for this reason.
> For cluster deployment, inject via K8s Secret.

**Setup:**

1. Obtain a LiteMaaS API key from the platform team
2. Create `.opencode/opencode.json`:
   ```json
   {
     "provider": {
       "litemaas": {
         "baseURL": "https://litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com/v1",
         "apiKey": "<your-api-key>",
         "models": {
           "Qwen3.6-35B-A3B": { "contextWindow": 131072 }
         }
       }
     }
   }
   ```
3. For K8s deployment, create a Secret:
   ```bash
   oc create secret generic litemaas-config \
     --from-file=opencode.json=.opencode/opencode.json
   ```

**Available Models:**

- `litemaas/Qwen3.6-35B-A3B` — investigation only (0% full pipeline, 67% investigation)

**Verify:**

```bash
opencode run -m litemaas/Qwen3.6-35B-A3B "echo hello"
```

## Agent Model Configuration

### Default Models (agent frontmatter)

Each agent has a default model in its `.opencode/agents/<name>.md` file:

| Agent | Default Model | Purpose |
|-------|--------------|---------|
| fix-investigate | Opus 4.6 | Investigation + plan |
| fix-implement | Opus 4.6 | Code fix + PR |
| review | Sonnet 4.6 | PR review |
| review-fix | Opus 4.6 | Fix review findings |
| audit-* (3 agents) | Sonnet 4.6 | Plan audit sub-agents |

### Override Precedence

Model selection follows this precedence (highest wins):

1. **CLI `-m` flag** — overrides everything for the main agent
   ```bash
   opencode run --agent fix-investigate -m ollama/deepseek-r1:32b "..."
   ```
2. **Agent frontmatter** — `model:` field in `.opencode/agents/<name>.md`
3. **Watcher env vars** — `FIX_MODEL`, `REVIEW_MODEL` in configmap.yaml

> **Note:** The `-m` flag overrides the MAIN agent only. Sub-agents
> (audit-architecture, audit-pe, audit-language) still use their own
> `model:` frontmatter. To override sub-agents, edit their agent files.

### Watcher Model Configuration

The watcher uses env vars to select models per phase (configmap.yaml):

| Variable | Default | Controls |
|----------|---------|----------|
| `FIX_MODEL` | `litemaas/Qwen3.6-35B-A3B` | Investigation + implementation agent |
| `REVIEW_MODEL` | `litemaas/Qwen3.6-35B-A3B` | Review agent |
| `REVIEW_FIX_MODEL` | `litemaas/Qwen3.6-35B-A3B` | Review-fix agent |
| `AUDIT_MODEL` | `litemaas/Qwen3.6-35B-A3B` | Audit sub-agents |

## Model Selection Guide

### By Scenario

| Scenario | Recommended | Why |
|----------|------------|-----|
| Full pipeline (investigate + implement + review) | Sonnet 4.6 via Vertex | 100% pass rate, cost-effective |
| Complex/high-priority issues | Opus 4.6 via Vertex | Premium reasoning, same 100% rate |
| Investigation only (no implementation) | LiteMaaS Qwen 3.6 or Ollama DeepSeek | Sufficient for root cause analysis |
| Local development/testing | Ollama DeepSeek R1 32B | No cloud dependency, fast iteration |
| Cluster without GCP credentials | LiteMaaS Qwen 3.6 | Only option — investigation phase only |

### Open Model Limitations

Open models (30-35B parameters) can identify root causes correctly but
struggle with the multi-phase implementation pipeline. The bottleneck is
instruction following and tool-call reliability, not reasoning capability.

Specifically:
- **Investigation phase**: Open models succeed 33-67% of the time
- **Implementation phase**: Open models fail to follow the structured
  skill phases (commit format, PR creation, label swaps)
- **Full pipeline**: Only Claude Opus/Sonnet complete all phases reliably

## Sandbox Network Policy

When running in OpenShell sandbox, the network policy must allow the
model provider's endpoints. The base policy (`policies/fix-investigate.yaml`)
includes Vertex AI and LiteMaaS. For Ollama, add:

```yaml
ollama:
  endpoints:
    - host: host.docker.internal
      port: 11434
      protocol: rest
      access: full
```

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Vertex AI auth fails | Missing/expired credentials | Run `gcloud auth application-default login` or check SA key path |
| Ollama tools appear as text | Context window too small | Ensure model has `contextWindow >= 32768` in opencode.json |
| LiteMaaS timeout | Rate limits | Retry after delay; check endpoint status |
| Model not found | Provider not configured | Check opencode.json (Ollama/LiteMaaS) or env vars (Vertex) |
| Sandbox can't reach model | Network policy missing endpoint | Add provider endpoint to sandbox policy YAML |
