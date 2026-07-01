# Quick Start — Fix a Bug Locally

Run agents directly on your machine with `opencode run`. No sandbox, no cluster.

## 1. Prerequisites

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

## 2. Set Credentials

Create a `.env` file in the project root (already gitignored):

```bash
JIRA_USERNAME=your@email.com
JIRA_API_TOKEN=your-jira-api-token       # https://id.atlassian.com/manage-profile/security/api-tokens
GITHUB_TOKEN=your-github-pat             # or: gh auth token
```

## 3. Choose a Model

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

## 4. Create a Jira Ticket

Add the `autofix` label and include the Agent Configuration in the description:

```markdown
[Describe the bug — what's broken, steps to reproduce, expected behavior]

## Agent Configuration
**Repository**: https://github.com/your-org/your-repo
**Branch**: main
```

## 5. Run the Agent

**Option A — Single issue (manual, no watcher):**

```bash
# Source credentials
set -a && source .env && set +a

# Step 1: Investigate — produces a fix plan
opencode run --agent fix-investigate \
  --dangerously-skip-permissions \
  -m $MODEL \
  "Investigate Jira ticket YOUR-TICKET-KEY. Follow the skill. FORK_MODE: $FORK_MODE. PLAN_IN_PR: $PLAN_IN_PR"

# Review the plan in Jira or on GitHub (.autofix/<PROJECT>/<TICKET>/fix-plan.md)
# Add bot-plan-approved label to authorize implementation

# Step 2: Implement — creates a PR
opencode run --agent fix-implement \
  --dangerously-skip-permissions \
  -m $MODEL \
  "Implement the approved fix for YOUR-TICKET-KEY. Follow the skill. FORK_MODE: $FORK_MODE. PLAN_IN_PR: $PLAN_IN_PR"

# Agent creates PR, updates Jira, swaps label to bot-ready-for-review
```

**Plan file behavior** — set `PLAN_IN_PR=false` to keep plan files out of
PRs (plan posted in Jira comment instead). See README Configuration table.

**Fork mode** — set `FORK_MODE=true` if the bot doesn't have push access
to the upstream repo. Agent will auto-fork, sync, push to fork, and create
cross-repo PRs (fork → upstream). Default `false` (push directly to ticket's
repo URL). See [Architecture.md — FORK_MODE Flag](Architecture.md#fork_mode-flag)
for the full workflow and token requirements.

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

## 6. What Happens Next

```
Investigate → Plan pushed to branch → HUMAN reviews plan → Implement →
PR created → Review Agent (3-lens) → Review-Fix (max 3 cycles) →
HUMAN approves PR → Merged
```

The agent updates Jira labels at each step. See the Label State Machine
in the main README for details.

## Notes

- `--dangerously-skip-permissions` is for local/eval runs only — skips
  interactive permission prompts. Do not use in production.
- For non-interactive runs (CI, scripts), wrap with `script -q <logfile>`
  to provide a PTY.
- Clean up cloned repos after runs: `rm -rf work/`
