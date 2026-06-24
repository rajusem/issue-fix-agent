# Issue Fix Agent

An automated issue-fixing system that watches Jira tickets labeled `autofix`
and dispatches AI agents to fix bugs, review code, and manage the full
lifecycle from ticket to merged PR.

> **Runtime:** OpenCode + OpenShell on OpenShift.
> **Model:** Qwen 3.6 35B via LiteMaaS (zero cloud credentials needed).
> **Status:** Full E2E pipeline verified with sandbox isolation.
> See `docs/Architecture.md` for the full design.

## How It Works

1. A user creates a Jira ticket with the `autofix` label and includes the repository URL in the description
2. The **Watcher** (Python, Deployment loop) polls Jira every 10 min, picks up the ticket, and dispatches the **Investigation Agent** inside an OpenShell sandbox
3. The **Investigation Agent** clones the repo, investigates the issue, writes a structured fix plan, and optionally runs it through 3 independent audit sub-agents (Architecture, PE, Language Expert) for review
4. After audit approval, the agent posts the plan to Jira and sets `bot-plan-ready` — a **human reviews and approves** the plan
5. After human approval (`bot-plan-approved`), the Watcher dispatches the **Implementation Agent** (sandboxed) which implements the fix, runs tests, and creates a PR
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

The old `**Skill**:` (singular) format is still accepted for backward
compatibility.

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

## Setup

### Local Development

- OpenCode v1.17.5+
- `gh` CLI with `contents:write` and `pull-requests:write` permissions
- `git` CLI

```bash
# Single cycle (local dev)
python -m orchestrator.watcher --dry-run

# Run investigation agent manually
opencode run --agent fix-investigate --dir /tmp "Investigate OBSINTA-123"
```

### OpenShift Deployment

See `local-docs/setup-openshift-cluster.md` for the full step-by-step guide.

**Quick start:**
```bash
# Build and push
podman build --platform linux/amd64 -t quay.io/rzalavad/issue-fix-agent:latest .
podman push quay.io/rzalavad/issue-fix-agent:latest

# Deploy (requires cluster-admin)
oc apply -f manifests/
# + OpenShell Helm install + SCCs + TLS certs (see setup guide)
```

### Credentials

| Credential | Stored as |
|------------|-----------|
| GitHub token | K8s Secret `watcher-secrets` |
| Jira API token | K8s Secret `watcher-secrets` |
| LiteMaaS API key | K8s Secret `litemaas-config` (in opencode.json) |

## Adapted From

This project adapts skills from the [AAP SDLC Harness](https://gitlab.cee.redhat.com/aap-sdlc/harness):

- `bugfix-workflow` → `issue-fix`
- `code-review` + `review-pr-workflow` → `issue-review`
- `git-workflow` patterns → embedded in `issue-fix` and `review-fix`
- `jira-integration` patterns → MCP-based Jira operations
- `ai-attribution` → Assisted-by trailer in all commits
