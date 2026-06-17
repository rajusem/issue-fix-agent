# Migration Plan: issue-fix-agent on OpenCode + OpenShell

> Date: 2026-06-17
> Direction: Company investing in OpenCode (L4 agent runtime) + OpenShell
> (L2 sandbox). Ambient Platform is deprioritized.

---

## Target Architecture

```
┌─────────────────────────────────────────────────────┐
│ OpenShell Sandbox (L2)                              │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Policy Engine (Landlock LSM)                    │ │
│ │ - Filesystem: only /workspace, /tmp             │ │
│ │ - Network: github.com, jira-site only           │ │
│ │ - Process: no privilege escalation              │ │
│ │                                                 │ │
│ │ ┌───────────────────────────────────────────┐   │ │
│ │ │ OpenCode (L4)                             │   │ │
│ │ │                                           │   │ │
│ │ │ opencode.json                             │   │ │
│ │ │ ├── agents/fix.md (Opus)                  │   │ │
│ │ │ ├── agents/review.md (Sonnet)             │   │ │
│ │ │ ├── agents/review-fix.md (Opus)           │   │ │
│ │ │ ├── skills/issue-fix/SKILL.md             │   │ │
│ │ │ ├── skills/issue-review/SKILL.md          │   │ │
│ │ │ ├── commands/fix-ticket.md                │   │ │
│ │ │ ├── mcp: mcp-atlassian (Jira)            │   │ │
│ │ │ └── AGENTS.md (security rules)            │   │ │
│ │ │                                           │   │ │
│ │ └───────────────────────────────────────────┘   │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## How issue-fix-agent Maps to OpenCode Concepts

| issue-fix-agent (Ambient) | OpenCode equivalent | Notes |
|---------------------------|-------------------|-------|
| `workflows/issue-fix/skills/issue-fix.md` | `.opencode/skills/issue-fix/SKILL.md` | Direct translation — skill files are markdown |
| `workflows/issue-review/skills/issue-review.md` | `.opencode/skills/issue-review/SKILL.md` | Same |
| `workflows/review-fix/skills/review-fix.md` | `.opencode/skills/review-fix/SKILL.md` | Same |
| `workflows/*/CLAUDE.md` | `.opencode/agents/fix.md`, `review.md` | Agent configs with model, permissions |
| `CLAUDE.md` (root) | `AGENTS.md` | Project-level rules, security constraints |
| `config/config.env` | `opencode.json` (models, providers) | Model assignments, MCP config |
| `config/projects.json` | `opencode.json` (custom config) or skill config | Allowlists, project settings |
| `ambient.json` | Not needed | OpenCode doesn't use this format |
| Watcher (Ambient session) | External orchestrator (cron + OpenCode CLI) | See below |
| `mcp__atlassian__*` | MCP server in `opencode.json` | mcp-atlassian as configured MCP |
| Ambient `create_session` MCP | External orchestrator + `openshell sandbox create -- opencode` | Sandbox creation replaces Ambient session dispatch |
| Session TTL | OpenShell sandbox timeout | Policy-level enforcement |
| Repo auto-clone (`repos` field) | `git clone` in sandbox or OpenCode workspace | Manual or scripted |

## What Mostly Translates Directly

### 1. Skill Files → OpenCode Skills

Our markdown skill files ARE OpenCode skills. The format is nearly
identical:

**Current (Ambient):**
```yaml
---
name: issue-fix
description: "Automated issue fixing skill..."
version: "1.1.0"
type: workflow
---
# Issue Fix Skill
## Phase 1: Understand
...
```

**OpenCode format:**
```yaml
---
name: issue-fix
description: "Automated issue fixing skill..."
---
# Issue Fix Skill
## Phase 1: Understand
...
```

The core skill logic (investigation strategies, audit loop, complexity
gate, security hardening, failure protocol) should transfer with limited
structural change, but tool names, session semantics, and runtime
behavior will need validation.

### 2. CLAUDE.md → AGENTS.md

Our root `CLAUDE.md` (security rules, label state machine, cross-workflow
contracts) becomes the `AGENTS.md` file in the OpenCode project. OpenCode
reads `AGENTS.md` and includes it in the LLM's context — same as Ambient
reads `CLAUDE.md`.

### 3. MCP Servers → OpenCode MCP Config

```json
// opencode.json
{
  "mcp": {
    "atlassian": {
      "type": "local",
      "command": "uvx",
      "args": ["mcp-atlassian",
        "--jira-url", "https://stage-redhat.atlassian.net",
        "--jira-username", "$JIRA_USERNAME",
        "--jira-api-token", "$JIRA_API_TOKEN"
      ]
    }
  }
}
```

OpenCode manages MCP servers natively — it starts them on demand, routes
tool calls, and handles auth. The `mcp__atlassian__*` tool names may
differ slightly but the functionality is the same.

### 4. Security Rules

Git hardening, URL validation, sensitive file blocklist, branch/commit
sanitization — all bash-level checks that work in any runtime.

### 5. Audit Sub-Agents

OpenCode has built-in subagent support. The 3 audit sub-agents
(Architecture, PE, Language Expert) can be defined as OpenCode agents:

```
.opencode/agents/audit-architecture.md
.opencode/agents/audit-pe.md
.opencode/agents/audit-language.md
```

Each with read-only permissions (no edit, no write, no bash write ops).

## What Changes Fundamentally

### 1. Watcher / Orchestrator

**Ambient:** Watcher is an Ambient session on a cron schedule that
dispatches child sessions via Ambient's session MCP.

**OpenCode + OpenShell:** No built-in session dispatch. Options:

**Option A — Cron + OpenCode CLI (simplest):**
```bash
# cron job every 20 min
opencode run --headless \
  --skill issue-fix \
  --input "Fix Jira ticket OBSINTA-123" \
  --model claude-opus-4-6
```
The watcher becomes a simple script that queries Jira (via curl/REST API),
identifies new `autofix` tickets, and runs `opencode` CLI for each.

**Option B — OpenCode Plugin (native):**
Build an OpenCode plugin that watches Jira and dispatches subagents.
OpenCode's plugin system supports TypeScript/JavaScript plugins with
lifecycle hooks.

**Option C — Kubernetes CronJob + OpenShell:**
```bash
# K8s CronJob creates a sandbox per ticket
openshell sandbox create \
  --policy fix-agent-policy.yaml \
  -- opencode run --headless --skill issue-fix
```

**Recommendation:** Start with Option A (simplest), evolve to Option C
for production.

### 2. Session Management

**Ambient:** Sessions have TTLs, auto-clone repos, track state.

**OpenShell:** Sandbox lifecycle is create → run → destroy. No built-in
session persistence. State must be managed by the agent (file-based,
similar to our `.audit/` approach) or by an external orchestrator.

OpenCode provides resumable session-oriented runtime behavior, but this
should not be treated as a direct replacement for Ambient session
semantics until validated in practice.

### 3. Multi-Agent Coordination

**Ambient:** Watcher creates separate sessions for fix, review, review-fix.
Each session is independent, coordinated via Jira labels + comments.

**OpenCode + OpenShell:** Two approaches:

**A. Same coordination (Jira labels + comments):**
Each agent runs in its own OpenShell sandbox, reads/writes Jira. The
external orchestrator (cron script or CronJob) checks Jira labels and
dispatches the right agent. This is closest to what we have.

**B. OpenCode subagents (new):**
OpenCode supports subagents — one agent can spawn another within the
same session. The fix agent could spawn review as a subagent. This
eliminates the watcher for the fix→review→review-fix flow, but adds
complexity within a single session.

**Recommendation:** Keep Jira-based coordination (Option A). It's proven,
debuggable, and decoupled.

### 4. Sandbox Policies

**New — OpenShell YAML policies for each agent role:**

```yaml
# fix-agent-policy.yaml
filesystem:
  read:
    - /workspace/**
    - /tmp/**
  write:
    - /workspace/**
    - /tmp/**
  deny:
    - /etc/**
    - /root/**

network:
  allow:
    - github.com:443
    - stage-redhat.atlassian.net:443
    - api.anthropic.com:443
  deny_all_others: true

process:
  deny:
    - privilege_escalation
    - new_namespaces
```

Different policies per agent role:
- **Fix agent:** read/write workspace, network to GitHub + Jira + LLM API
- **Review agent:** read-only workspace (no write), network to GitHub + Jira + LLM API
- **Watcher:** no workspace access, network to Jira only

## Migration Phases

### Phase 1: Translate Skills to OpenCode Format (1 week)

**What changes:**
- Move `workflows/issue-fix/skills/issue-fix.md` → `.opencode/skills/issue-fix/SKILL.md`
- Move `workflows/issue-review/skills/issue-review.md` → `.opencode/skills/issue-review/SKILL.md`
- Move `workflows/review-fix/skills/review-fix.md` → `.opencode/skills/review-fix/SKILL.md`
- Create agent configs: `.opencode/agents/fix.md`, `review.md`, `review-fix.md`
- Rename `CLAUDE.md` → `AGENTS.md`
- Create `opencode.json` with model + MCP config
- Remove Ambient-specific references (ambient.json, session dispatch, `mcp__acp__*`)
- Update MCP tool names to match mcp-atlassian's actual tool names

**What stays the same:**
- All skill logic (investigation, audit loop, review methodology)
- Security hardening (git, URL, sensitive files)
- Label state machine (Jira labels)
- Cross-workflow contracts (Jira comments)

**Effort:** Low — mostly file moves + renaming + removing Ambient references

### Phase 2: Build Watcher as External Script (1 week)

**What:**
- Python/bash script that queries Jira (REST API) for `autofix` tickets
- Dispatches `opencode run --headless` per ticket
- Manages label state machine (same as current watcher)
- Runs as a cron job (or K8s CronJob)

This replaces the Ambient watcher session. The script is simpler because
it doesn't need MCP — it uses direct Jira REST API (curl or Python
requests).

### Phase 3: Add OpenShell Sandboxing (1 week)

**What:**
- Define OpenShell policies per agent role (fix, review, review-fix)
- Watcher script creates sandboxes: `openshell sandbox create -- opencode run ...`
- Test sandbox isolation (filesystem, network)

### Phase 4: Test End-to-End on OBSINTA (1 week)

**What:**
- Run the full pipeline on staging tickets
- Validate: ticket → fix → review → review-fix → merge
- Collect data: fix quality, costs, failure modes

---

## Decision Points

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Agent runtime | OpenCode CLI headless | OpenCode — company direction |
| Sandbox | OpenShell | OpenShell — company direction |
| Watcher | Python script + cron vs. K8s CronJob vs. OpenCode plugin | Python script for MVP, K8s CronJob for production |
| Jira integration | mcp-atlassian MCP vs. direct REST API | MCP (OpenCode manages it natively), REST fallback |
| Multi-agent coordination | Jira labels (current) vs. OpenCode subagents | Jira labels — proven, decoupled, debuggable |
| Model provider | Claude-only vs. LiteLLM multi-model | Start Claude-only, add multi-model later via OpenCode's provider system |
| State persistence | File-based (.audit/) vs. OpenCode sessions | OpenCode sessions (event-sourced, resumable) + .audit/ for artifacts |

---

## What We Lose vs What We Gain

### Lose
- Ambient's one-click session creation (replaced by CLI/script)
- Ambient's MCP hosting via Integrations page (must run mcp-atlassian ourselves)
- Ambient's UI for monitoring sessions (replaced by logs/Jira)
- Zero-code workflow changes (now need to understand opencode.json + agents)

### Gain
- **No platform risk** — OpenCode + OpenShell are open-source, company-backed
- **Kernel-level security** — OpenShell Landlock vs. container-level only
- **Multi-model** — OpenCode supports 20+ providers out of the box
- **Plugin ecosystem** — TypeScript plugins for custom extensions
- **Headless CI/CD** — `opencode run` in any CI pipeline
- **No MCP blocking** — run mcp-atlassian locally, no platform dependency
- **Faster iteration** — OpenCode skills + agents are just files, no deploy
