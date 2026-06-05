# Issue Fix Agent

An automated issue-fixing system that watches Jira tickets and dispatches AI agents to fix bugs, review code, and manage the full lifecycle from ticket to merged PR.

## How It Works

1. A user creates a Jira ticket with the `autofix` label and includes the repository URL in the description
2. The **Watcher** polls Jira on a schedule, picks up the ticket, and dispatches a **Fix Agent**
3. The **Fix Agent** clones the repo, investigates the issue, implements a fix, creates a PR, and updates Jira
4. The **Review Agent** reviews the PR through 3 lenses (correctness, security, quality)
5. If the review finds issues, the **Review-Fix Agent** addresses them and sends back for re-review (max 3 cycles)
6. When the review passes, a human approves and merges the PR
7. The Watcher detects the merge and updates Jira with the `bot-merged` label

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
| `bot-missing-info` | Ticket missing required info (repo URL) — user removes after adding |
| `bot-in-progress` | Fix agent is working on it |
| `bot-ready-for-review` | PR created, awaiting agent review |
| `bot-review-fix` | Review found issues, review-fix agent is addressing them |
| `bot-review-complete` | Agent review passed, awaiting human approval |
| `bot-merged` | PR merged, ticket ready for manual close |
| `bot-fix-failed` | Agent could not fix — needs human attention |
| `no-autofix` | Opt-out — ticket excluded from automation while keeping `autofix` label |

## Project Structure

```
workflows/
├── jira-watcher/     # Cron-spawned poller and orchestrator
├── issue-fix/        # Bug investigation and fix agent
├── issue-review/     # Code review agent (3-lens, no-approve)
└── review-fix/       # Address review findings agent
config/
├── config.env        # Models, TTLs, concurrency limits
└── projects.json     # Watched projects, skill URL allowlist
```

## Setup

### Prerequisites

- Ambient Platform access with a project configured
- `mcp-atlassian` MCP server configured for Jira access
- `session` MCP server (built-in Ambient) for spawning child sessions
- GitHub token with `contents: write` and `pull-requests: write` permissions

### Configuration

1. Edit `config/projects.json` — set your Jira project keys and skill URL patterns
2. Edit `config/config.env` — set your Jira site, models, TTLs
3. Configure Ambient environment variables:
   - `JIRA_SITE` — Your Atlassian cloud instance
   - `GITHUB_TOKEN` — GitHub App token (preferred) or PAT
   - `SLACK_WEBHOOK_URL` — For notifications (optional)

### Running

Create a watcher session in Ambient pointing to the `workflows/jira-watcher/` workflow. Set it on a cron schedule (recommended: every 20 minutes).

## Adapted From

This project adapts skills from the [AAP SDLC Harness](https://gitlab.cee.redhat.com/aap-sdlc/harness) for unattended Ambient Platform operation:

- `bugfix-workflow` → `issue-fix`
- `code-review` + `review-pr-workflow` → `issue-review`
- `git-workflow` patterns → embedded in `issue-fix` and `review-fix`
- `jira-integration` patterns → MCP-based Jira operations
- `ai-attribution` → Assisted-by trailer in all commits
