# Issue Fix Agent

An automated issue-fixing system that watches Jira tickets labeled `autofix`
and dispatches AI agents to fix bugs, review code, and manage the full
lifecycle from ticket to merged PR.

> **Runtime:** OpenCode (agent runtime). OpenShell + OpenShift deployment is WIP.
> **Model:** Claude Sonnet 4.6 (default). Also supports open models via Ollama/LiteMaaS — see Model Recommendations.
> **Status:** E2E pipeline verified locally (7 models evaluated). OpenShell sandbox + OpenShift cluster deployment in progress.
> See `docs/Architecture.md` for the full design.

## How It Works

```mermaid
flowchart LR
    A["🎫 Jira<br>autofix"] --> B["👁 Watcher"]

    subgraph INV["INVESTIGATE (Phases 0-4)"]
        C["📂 Clone +<br>Root Cause"] --> D["📝 Plan +<br>3-Agent Audit"]
    end

    B --> C
    D --> E

    E["🧑 GATE 1<br>Human Plan<br>Review"]:::gate

    subgraph IMPL["IMPLEMENT (Phases 5-11)"]
        F["⚙️ Code Fix +<br>Tests +<br>Blocklist"] --> G["📤 Create PR +<br>Jira Telemetry"]
    end

    E -->|approved| F

    subgraph REV["REVIEW"]
        H["🔎 3-Lens<br>Correctness<br>Security<br>Quality"]
        H -->|findings| I["🔧 Review Fix"]
        I -->|"< 3 cycles"| H
        H -->|clean| J["✅ Done"]
    end

    G --> H

    J --> K["🧑 GATE 2<br>Human PR<br>Review"]:::gate
    K -->|approved| L["🚀 Merged"]:::merged

    I -->|"3 cycles"| M["⚠️ Escalate"]:::fail
    M -.->|"bot-retry<br>(max 2x)"| B

    classDef gate fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    classDef fail fill:#ffebee,stroke:#c62828,stroke-width:2px
    classDef merged fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style INV fill:#e3f2fd,stroke:#1565c0
    style IMPL fill:#e8f5e9,stroke:#2e7d32
    style REV fill:#f3e5f5,stroke:#7b1fa2
```

### Step-by-step

1. A user creates a Jira ticket with the `autofix` label and includes the repository URL in the description
2. The **Watcher** (Python, Deployment loop) polls Jira every 20 min (configurable via `JIRA_POLL_INTERVAL`), picks up the ticket, and dispatches the **Investigation Agent** (locally or inside an OpenShell sandbox when deployed on cluster)
3. The **Investigation Agent** clones the repo, investigates the issue, writes a structured fix plan, and optionally runs it through 3 independent audit sub-agents (Architecture, PE, Language Expert) for review
4. After audit approval, the agent posts the plan to Jira and sets `bot-plan-ready` — a **human reviews and approves** the plan
5. After human approval (`bot-plan-approved`), the Watcher dispatches the **Implementation Agent** which implements the fix, runs tests, and creates a PR
6. The **Review Agent** reviews the PR through 3 lenses (correctness, security, quality)
7. If the review finds issues, the **Review-Fix Agent** addresses them and sends back for re-review (max 3 cycles)
8. When the review passes, a human approves and merges the PR
9. The Watcher detects the merge and updates Jira with the `bot-merged` label

## Jira Ticket Format

Add these fields to the ticket description:

```markdown
[Issue description — what's broken, steps to reproduce, expected behavior]

The agent analyzes the description to choose an investigation strategy.
Signals like "was working before" trigger git history analysis; "intermittent"
triggers concurrency analysis. Be descriptive about the problem behavior.

---
## Agent Configuration
**Repository**: https://github.com/org/repo          (REQUIRED)
**Branch**: main                                      (optional)
**Commit**: abc1234def                                (optional — investigate this specific commit)
**Skills**:                                           (optional — multiple guidance URLs)
  - https://raw.githubusercontent.com/org/repo/main/.claude/skills/conventions.md
  - https://raw.githubusercontent.com/org/repo/main/.claude/skills/testing.md
**Knowledge Repo**: https://github.com/org/team-docs  (optional — cloned for context)
```


## Label State Machine

| Label | Meaning |
|-------|---------|
| `autofix` | Permanent marker — ticket should be handled by automation |
| `bot-missing-info` | Ticket missing required info — bot re-checks automatically each cycle |
| `bot-in-progress` | Fix agent is working on it |
| `bot-plan-ready` | Plan approved by auditors, awaiting human review |
| `bot-plan-approved` | Human adds this to authorize implementation (also accepts `bot-proceed`) |
| `bot-ready-for-review` | PR created, awaiting agent review |
| `bot-review-fix` | Review found issues, review-fix agent is addressing them |
| `bot-review-complete` | Agent review passed, awaiting human approval |
| `bot-merged` | PR merged, ticket ready for manual close |
| `bot-fix-failed` | Agent could not fix — needs human attention |
| `no-autofix` | Opt-out — ticket excluded from automation while keeping `autofix` label |
| `bot-retry` | Retry — user adds to `bot-fix-failed` ticket to trigger re-processing (max 2) |
| `bot-cancelled` | Human override — stops active sessions, returns ticket to failed state |

## Project Structure

```
.opencode/
├── agents/           # Agent definitions (fix-investigate, fix-implement, review, review-fix, 3 audit)
├── skills/           # Skill files (issue-investigate, issue-implement, issue-review, review-fix)
├── plugins/          # Safety hooks (block-destructive.js)
└── settings.json     # Pre-allowed permissions for unattended agents
orchestrator/
├── watcher.py        # Jira polling, label state machine, 9 phases
├── dispatcher.py     # Agent dispatch with OpenShell sandbox support
├── jira_client.py    # REST API client for Jira (v3 ADF parsing)
├── config.py         # Config from env vars + projects.json
└── models.py         # Data models (Ticket, CycleStats)
policies/             # OpenShell sandbox policies (filesystem + network)
manifests/            # K8s manifests (namespace, RBAC, PVC, secrets, deployment)
local-docs/           # Setup guides, learnings, model evaluation (not committed to upstream)
docs/
├── Architecture.md   # System design and deployment
└── ...               # Analysis, plans, testing
Containerfile         # UBI9 image with OpenCode, OpenShell, toolchain
opencode.json         # OpenCode config — MCP servers, instructions
AGENTS.md             # Project rules loaded into agent context
```

## Quick Start — Fix a Bug Locally

### 1. Prerequisites

```bash
# OpenCode (AI agent runtime)
npm i -g opencode                        # or: curl -fsSL https://opencode.ai/install.sh | sh
opencode --version                       # v1.17.11+

# GitHub CLI (for PR creation)
gh auth status                           # must be authenticated

# Python deps (for watcher, optional)
uv pip install -r orchestrator/requirements.txt   # or: pip install -r orchestrator/requirements.txt

# Jira MCP server (for Jira integration)
pip install mcp-atlassian                # or: uvx mcp-atlassian
```

### 2. Set Credentials

Create a `.env` file in the project root (already gitignored):

```bash
JIRA_USERNAME=your@email.com
JIRA_API_TOKEN=your-jira-api-token       # https://id.atlassian.com/manage-profile/security/api-tokens
GITHUB_TOKEN=your-github-pat             # or: gh auth token
```

### 3. Choose a Model

```bash
# Option A: Vertex AI (recommended — highest reliability)
# Requires: gcloud auth, GOOGLE_CLOUD_PROJECT env var
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project
MODEL="google-vertex-anthropic/claude-sonnet-4-6@default"

# Option B: Local Ollama (free, works offline)
ollama serve &
ollama pull deepseek-r1:32b              # or: gemma4:31b
MODEL="ollama/deepseek-r1:32b"

# Option C: LiteMaaS (Red Hat internal shared gateway)
# Edit .opencode/opencode.json with your LiteMaaS API key
MODEL="litemaas/Qwen3.6-35B-A3B"
```

### 4. Create a Jira Ticket

Add the `autofix` label and include the Agent Configuration in the description:

```markdown
[Describe the bug — what's broken, steps to reproduce, expected behavior]

## Agent Configuration
**Repository**: https://github.com/your-org/your-repo
**Branch**: main
```

### 5. Run the Agent

**Option A — Single issue (manual, no watcher):**

```bash
# Source credentials
set -a && source .env && set +a

# Step 1: Investigate — produces a fix plan
opencode run --agent fix-investigate \
  --dangerously-skip-permissions \
  -m $MODEL \
  "Investigate Jira ticket YOUR-TICKET-KEY. Follow the skill."

# Review the plan on GitHub (.autofix/<PROJECT>/<TICKET>/fix-plan.md)
# Then swap label: bot-plan-ready → bot-in-progress

# Step 2: Implement — creates a PR
opencode run --agent fix-implement \
  --dangerously-skip-permissions \
  -m $MODEL \
  "Implement the approved fix for YOUR-TICKET-KEY. Follow the skill."

# Agent creates PR, updates Jira, swaps label to bot-ready-for-review
```

**Option B — Watcher (automated, polls Jira):**

```bash
set -a && source .env && set +a

# Dry run first (no mutations)
python -m orchestrator.watcher --dry-run

# Single cycle (processes all autofix tickets once)
python -m orchestrator.watcher

# Continuous loop (polls every 20 min, SIGTERM to stop)
python -m orchestrator.watcher --loop
```

### 6. What Happens Next

```
Investigate → Plan pushed to branch → HUMAN reviews plan → Implement →
PR created → Review Agent (3-lens) → Review-Fix (max 3 cycles) →
HUMAN approves PR → Merged
```

The agent updates Jira labels at each step. Check the Label State Machine
below for details.

### Notes

- `--dangerously-skip-permissions` is for local/eval runs only — skips
  interactive permission prompts. Do not use in production.
- For non-interactive runs (CI, scripts), wrap with `script -q <logfile>`
  to provide a PTY.
- Clean up cloned repos after runs: `rm -rf target-repo/`

## Local Development

> Full guide: `local-docs/local-development-guide.md`

### Model Recommendations

Agent definitions default to `google-vertex-anthropic/claude-sonnet-4-6` but
you can override at runtime with `-m`. The pipeline requires strong
instruction-following and multi-step tool execution — not all models can
reliably complete the full 11-phase workflow.

| Provider | Model ID | Notes |
|----------|----------|-------|
| Vertex AI | `google-vertex-anthropic/claude-sonnet-4-6` | Recommended default — handles all issue types |
| Vertex AI | `google-vertex-anthropic/claude-opus-4-6` | For complex or high-priority issues |
| Ollama | `ollama/deepseek-r1:32b` | Fast local option — works for simple, well-scoped bugs |
| Ollama Cloud | `ollama/minimax-m2.5:cloud` | Cloud-hosted open model — works for simple bugs |
| LiteMaaS | `litemaas/Qwen3.6-35B-A3B` | Cluster-compatible — can investigate but struggles with implementation |
| Ollama | `ollama/gemma4:31b` | Local testing only — slow inference, limited reliability |
| Ollama | `ollama/qwen3-coder-fixed` | Not recommended — poor instruction following |

> **Note:** Open models (30-35B) can often identify root causes correctly but
> struggle with the multi-phase implementation pipeline. The bottleneck is
> instruction following and tool-call reliability, not reasoning capability.
> Run your own eval with `eval/run-eval.sh` to benchmark models on your issues.

## OpenShift Deployment (WIP)

> **Status:** Infrastructure scaffolding ready (manifests, Containerfile,
> policies). Full E2E validation on OpenShift with OpenShell sandbox
> isolation is in progress.
>
> Full guide: `local-docs/setup-openshift-cluster.md`

```bash
# Build and push
podman build --platform linux/amd64 -t quay.io/rzalavad/issue-fix-agent:latest .
podman push quay.io/rzalavad/issue-fix-agent:latest

# Deploy (requires cluster-admin)
oc apply -f manifests/
# + OpenShell Helm install + SCCs + TLS certs (see setup guide)
```

### Credentials

| Credential | Where | Stored as |
|------------|-------|-----------|
| GitHub token | Local: `$GITHUB_TOKEN` env var | Cluster: K8s Secret `watcher-secrets` |
| Jira API token | Local: `$JIRA_API_TOKEN` env var | Cluster: K8s Secret `watcher-secrets` |
| LiteMaaS API key | Local: `.opencode/opencode.json` | Cluster: K8s Secret `litemaas-config` |

## Documentation

| Doc | Purpose |
|-----|---------|
| `docs/Architecture.md` | System design, label state machine, audit loop |
| `local-docs/local-development-guide.md` | Detailed local setup, provider config, model selection |
| `local-docs/setup-openshift-cluster.md` | Step-by-step cluster deployment (40 issues documented) |
| `eval/README.md` | Model evaluation results and benchmarking scripts |
| `local-docs/demo-token-savings.md` | Token optimization layers (RTK, Ponytail, model routing) |
| `local-docs/learnings.md` | 40 lessons from development and deployment |

## Inspired By

Initial skill patterns inspired by the [AAP SDLC Harness](https://gitlab.cee.redhat.com/aap-sdlc/harness)
(bugfix-workflow, code-review, git-workflow, jira-integration, ai-attribution).
Skills have since been rewritten for OpenCode with structured playbooks,
audit sub-agents, and MCP-based Jira integration.
