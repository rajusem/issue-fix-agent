# Issue Fix Agent

An automated issue-fixing system that watches Jira tickets labeled `autofix`
and dispatches AI agents to fix bugs, review code, and manage the full
lifecycle from ticket to merged PR.

> **Runtime:** OpenCode + OpenShell (migrated from Ambient Platform).
> See `docs/Architecture.md` and `docs/plan-opencode-openshell-migration.md`
> for the full design.

## How It Works

1. A user creates a Jira ticket with the `autofix` label and includes the repository URL in the description
2. The **Watcher** polls Jira on a schedule, picks up the ticket, and dispatches the **Investigation Agent**
3. The **Investigation Agent** clones the repo, investigates the issue, writes a structured fix plan, and runs it through 3 independent audit sub-agents (Architecture, PE, Language Expert) for review
4. After audit approval, the agent posts the plan to Jira and sets `bot-plan-ready` — a **human reviews and approves** the plan
5. After human approval (`bot-proceed`), the Watcher dispatches the **Implementation Agent** which implements the fix, runs tests, and creates a PR
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
| `bot-proceed` | Human adds this to authorize implementation |
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
├── agents/           # Agent definitions (fix, review, review-fix, 3 audit)
├── skills/           # Skill files (issue-fix, issue-review, review-fix)
└── plugins/          # Safety hooks (block-destructive.js)
config/
├── config.env        # Models, TTLs, concurrency limits
└── projects.json     # Watched projects, skill URL allowlist
docs/
├── Architecture.md   # System design and deployment
├── reference/        # Watcher spec (Phase 2 input)
└── ...               # Analysis, plans, testing
opencode.json         # OpenCode config — MCP servers, instructions
AGENTS.md             # Project rules loaded into agent context
```

## Setup

### Prerequisites

- OpenCode v1.17.5+
- `mcp-atlassian` MCP server (`uvx mcp-atlassian`)
- `gh` CLI with `contents:write` and `pull-requests:write` permissions
- `git` CLI

### Configuration

1. Edit `config/projects.json` — set your Jira project keys and skill URL patterns
2. Edit `config/config.env` — set models, TTLs, concurrency limits
3. Set environment variables:
   - `JIRA_USERNAME` / `JIRA_API_TOKEN` — Jira credentials
   - `GITHUB_TOKEN` — GitHub App token (preferred) or PAT
   - `ANTHROPIC_API_KEY` — For OpenCode agent dispatch

### Running

```bash
# Verify OpenCode can start in this project
opencode run "What skills are available?"

# Run the fix agent against a ticket (Phase 2 watcher will automate this)
opencode run --agent fix "Fix Jira ticket OBSINTA-123"
```

## Adapted From

This project adapts skills from the [AAP SDLC Harness](https://gitlab.cee.redhat.com/aap-sdlc/harness):

- `bugfix-workflow` → `issue-fix`
- `code-review` + `review-pr-workflow` → `issue-review`
- `git-workflow` patterns → embedded in `issue-fix` and `review-fix`
- `jira-integration` patterns → MCP-based Jira operations
- `ai-attribution` → Assisted-by trailer in all commits
