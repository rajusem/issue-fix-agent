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
│ │ │ ├── mcp: mcp-atlassian (Jira)            │   │ │
│ │ │ └── AGENTS.md (security rules)            │   │ │
│ │ │                                           │   │ │
│ │ └───────────────────────────────────────────┘   │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## Architectural Requirements

These principles govern all implementation decisions. They are not
Phase-specific — they apply from day one.

### 1. Control-Plane Vocabulary

| Term | Definition | Example |
|------|-----------|---------|
| **Ticket** | Business unit — a Jira issue being processed | OBSINTA-123 |
| **Run** | One execution attempt for a ticket-stage pair | run-obsinta-123-fix-1 |
| **Stage** | A pipeline step with its own agent and sandbox | fix, review, review-fix |
| **Agent Role** | The persona and model assigned to a stage | fix=Opus, review=Sonnet |
| **Artifact** | Durable output of a run | plan.json, findings.json, run-metadata.json |
| **Orchestrator** | The control plane that dispatches runs | Python watcher script |

The orchestrator owns run lifecycle (dispatch, monitor, retry, cancel,
cleanup). Agents own stage execution (investigate, fix, review). Jira
owns business state (labels, comments). Artifacts own execution state
(plans, findings, telemetry).

### 2. Action Classification

All agent actions fall into three categories. This model should be
encoded in AGENTS.md and enforced via PreToolUse hooks + OpenShell
policies.

**Allow automatically:**
- Read-only repo inspection (grep, file read, git log)
- Local tests, static analysis, linting
- Non-destructive Jira reads and comments
- Branch creation, commits, pushes to feature branches

**Require approval (or explicit skill instruction):**
- PR creation
- Jira status transitions (In Progress, Done, Closed)
- Execution against repos outside the configured allowlist
- Any action with external side effects beyond the normal fix flow

**Always block:**
- `git push --force`, `git reset --hard` on any branch
- `git checkout .`, `git clean -fd` (destroys uncommitted work)
- Writes outside `/workspace` and `/tmp`
- Network egress outside approved destinations
- Access to credentials not injected via environment
- `rm -rf /`, `chmod 777`, privilege escalation

### 3. Secret Handling

**Non-negotiable principle:** No secret entry or approval tokens through
prompt text. Credentials come from environment injection only.

- Secrets (`GITHUB_TOKEN`, `JIRA_API_TOKEN`, `JIRA_USERNAME`) are
  injected into sandboxes via OpenShell `--env` or K8s secrets
- Agent-visible environment should be minimal and role-scoped
  (review agent should not have push credentials)
- The curl fallback for Jira label operations uses `$JIRA_API_TOKEN`
  as a bash env var — this is correct (never in prompt text)
- Approvals (human PR merge) should not require exposing secrets
  back into chat

### 4. Recovery Operations

The orchestrator must support these operations explicitly:

| Operation | Trigger | What Happens |
|-----------|---------|-------------|
| **dispatch** | New autofix ticket or stage transition | Create sandbox, run agent |
| **retry** | User adds `bot-retry` label | Remove bot-fix-failed, re-dispatch with prior failure context |
| **cancel** | User adds `bot-cancelled` label | Stop sandbox, clean up labels, move to bot-fix-failed |
| **cleanup** | Stale run detected (>4h in bot-in-progress) | Check sandbox status, clean up orphaned state |
| **resume** | Agent context compressed mid-run | Agent reads `.fix-state.yaml` to recover phase/progress |
| **close** | PR merged, watcher detects | Swap to bot-merged, post completion comment |

Each operation must be **idempotent** — running it twice on the same
ticket-run produces the same result.

### 5. Run Metadata Schema

Every run produces a `run-metadata.json` artifact with these fields.
This enables per-stage observability, cost attribution, and audit trails.

```json
{
  "ticket_key": "OBSINTA-123",
  "run_id": "run-obsinta-123-fix-1",
  "stage": "fix",
  "agent_role": "fix",
  "model": "anthropic/claude-opus-4-6",
  "sandbox_id": "openshell-abc123",
  "started_at": "2026-06-17T10:30:00Z",
  "ended_at": "2026-06-17T12:45:00Z",
  "duration_minutes": 135,
  "outcome": "success | failure | timeout | cancelled",
  "failure_phase": null,
  "retry_count": 0,
  "audit_iterations": 2,
  "tokens_input": null,
  "tokens_output": null,
  "cost_estimate_usd": null,
  "pr_url": "https://github.com/org/repo/pull/42",
  "artifacts": [
    "fix-plan.json",
    "validation.json",
    "run-metadata.json"
  ]
}
```

For MVP, this file is written to `.audit/run-metadata.json` inside the
sandbox (alongside existing `.audit/approved-plan.md` and
`.audit/validation.json`).

**Sandbox artifact extraction:** OpenShell sandboxes are ephemeral —
artifacts inside `.audit/` are destroyed when the sandbox is removed.
The watcher MUST extract artifacts BEFORE destroying the sandbox:
```
openshell sandbox copy <sandbox-id>:/workspace/.audit/ ./runs/<run-id>/
openshell sandbox destroy <sandbox-id>
```
Extracted artifacts are appended to `runs.jsonl` by the watcher
(single-writer, sequential — no concurrent PVC write issues). For
production, export to a durable store outside Jira for analytics
and audit.

---

## Prerequisites

Before starting Phase 1:
- Install OpenCode (v1.17+) and verify `opencode run "hello"` works
- Read OpenCode docs: [Agents](https://opencode.ai/docs/agents/),
  [Skills](https://opencode.ai/docs/skills/), [MCP Servers](https://opencode.ai/docs/mcp-servers/),
  [Config](https://opencode.ai/docs/config/)
- Verify OpenCode CLI flags: `opencode run --help` — confirm `--headless`
  or equivalent non-interactive mode exists
- Install OpenShell and verify `openshell sandbox create -- echo hello` works
- Verify mcp-atlassian runs locally: `uvx mcp-atlassian --help`
- Key concepts: agents (persona configs), skills (SKILL.md workflows),
  AGENTS.md (project rules), opencode.json (central config)

## How issue-fix-agent Maps to OpenCode Concepts

| issue-fix-agent (Ambient) | OpenCode equivalent | Notes |
|---------------------------|-------------------|-------|
| `workflows/issue-fix/skills/issue-fix.md` | `.opencode/skills/issue-fix/SKILL.md` | Skill files are markdown — translate body references |
| `workflows/issue-review/skills/issue-review.md` | `.opencode/skills/issue-review/SKILL.md` | Same |
| `workflows/review-fix/skills/review-fix.md` | `.opencode/skills/review-fix/SKILL.md` | Same |
| `workflows/issue-fix/skills/investigation-strategies.md` | `.opencode/skills/issue-fix/investigation-strategies.md` | Referenced by fix skill for signal-based investigation |
| `workflows/issue-fix/skills/audit-prompts/*.md` (3 files) | `.opencode/agents/audit-architecture.md`, `audit-pe.md`, `audit-language.md` | Sub-agent prompt templates become agent definitions with locked-down permissions |
| `workflows/*/CLAUDE.md` (3 agent files) | `.opencode/agents/fix.md`, `review.md`, `review-fix.md` | Agent configs with model, permissions. Watcher CLAUDE.md is NOT migrated — watcher is a Python script, not an OpenCode agent. |
| `CLAUDE.md` (root) | `AGENTS.md` | Project-level rules, security constraints |
| `config/config.env` | `opencode.json` (models, providers) | Model assignments, MCP config |
| `config/projects.json` | `opencode.json` (custom config) or skill config | Allowlists, project settings |
| `workflows/*/ambient.json` (4 files) | Not needed | Metadata (name, description, version) moves to agent definitions |
| Watcher (Ambient session) | External orchestrator (cron + OpenCode CLI) | See below |
| `mcp__atlassian__*` | MCP server in `opencode.json` | Tool names may differ — must validate |
| Ambient `create_session` MCP | External orchestrator + `openshell sandbox create -- opencode` | Sandbox creation replaces Ambient session dispatch |
| Session TTL | OpenShell sandbox timeout | Policy-level enforcement |
| Repo auto-clone (`repos` field) | `git clone` in sandbox or OpenCode workspace | Manual or scripted |
| `MAX_CONCURRENT_*` (config.env) | Concurrency control in external watcher script | No built-in limit in OpenCode — watcher must enforce |

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
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "anthropic": {}
  },
  "mcp": {
    "atlassian": {
      "type": "local",
      "command": ["uvx", "mcp-atlassian",
        "--jira-url", "https://stage-redhat.atlassian.net"],
      "environment": {
        "JIRA_USERNAME": "",
        "JIRA_API_TOKEN": ""
      }
    }
  }
}
```

Note: `command` is a single array (no separate `args` field). Credentials
go in `environment` object, injected at runtime via K8s Secrets or
OpenShell `--env`. This format is identical to the example in
Architecture.md.

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
- **Review agent:** write during setup (git clone + gh pr checkout),
  then read-only for the review itself. No push credentials. Network
  to GitHub + Jira + LLM API
- **Watcher:** no workspace access, network to Jira only

## Migration Phases

### Phase 0: Observability Foundation (1 week)

**Why first:** Cannot operate what you cannot observe. If a sandbox
crashes, an agent hangs, or costs spike — without observability, tickets
silently stall and money burns. This phase is non-negotiable before
any agent runs in production.

**What:**
- Watcher script emits structured JSON logs (one line per action:
  dispatch, label swap, sandbox create/destroy, error)
- Each agent run writes `run-metadata.json` (using the schema from
  Architectural Requirements §5) to `.audit/` at run completion
  or failure
- Collection script gathers `run-metadata.json` from completed runs
  into a single `runs.jsonl` append-only log file
- Alert script checks `runs.jsonl` for:
  - Sandbox creation failure (>3 in 10 minutes → CRITICAL)
  - Agent running > TTL with no Jira update (→ CRITICAL)
  - Fix success rate < 50% over rolling 24h (→ HIGH)
  - Cost estimate > $50 per ticket (→ HIGH, typical is $10-30)
  - Tickets stale in bot-in-progress > 4h (→ HIGH)
- Alerts delivered via Slack webhook (same `SLACK_WEBHOOK_URL` as
  watcher cycle summary)

**What this is NOT:**
- Not Prometheus/Grafana (add later when volume justifies)
- Not LangFuse (add when token-level tracking is needed)
- Not a database (append-only JSONL file is sufficient for MVP)

**Done when:**
- Watcher produces parseable JSON logs
- `run-metadata.json` is written by at least the fix agent
- Alert script fires correctly when injecting a test failure
- Slack receives alert messages

**Effort:** 1 week. The run-metadata.json schema is already defined.
The alert rules are simple threshold checks on JSONL data.

**Future upgrade:** If the target OpenShift cluster has centralized
logging (FluentBit, Splunk, ELK, Datadog), configure a log forwarder
for `runs.jsonl` instead of the custom alert script. The JSONL format
is already compatible with standard log ingestion pipelines.

### Phase 1: Translate Skills to OpenCode Format (1-2 weeks)

**What changes:**
- Move skill files to `.opencode/skills/*/SKILL.md` (see mapping table)
- Move investigation-strategies.md alongside the fix skill
- Create agent configs: `.opencode/agents/fix.md`, `review.md`,
  `review-fix.md`, `audit-architecture.md`, `audit-pe.md`,
  `audit-language.md` (with explicit locked-down permissions)
- Rename `CLAUDE.md` → `AGENTS.md`
- Create `opencode.json` with model + MCP config
- Remove Ambient-specific references throughout skill bodies
  ("Ambient session", "Ambient Platform", session dispatch references)
- Validate and update MCP tool names to match mcp-atlassian's actual
  names in OpenCode (run mcp-atlassian locally, list tools, update all
  references in skill files)
- Remove ambient.json files (metadata moves to agent definitions)
- Add `.opencode/hooks/block-destructive.sh` — PreToolUse hook that
  blocks destructive commands (`git push --force`, `git reset --hard`,
  `rm -rf /`, `chmod 777`) at the tool level, not just prompt level.
  This enforces safety guarantees that skill files only request.
- Add self-critique scoring to the review agent skill — before posting
  `## Agent Code Review`, the review agent scores its findings on
  Accuracy, Completeness, Confidence (0.0-1.0). Findings with
  confidence < 0.7 are flagged for human attention. This catches
  uncertain findings before they trigger a review-fix cycle.
- Add structured `.audit/fix-plan.json` alongside the markdown plan —
  machine-readable version with file list, change descriptions, and
  expected test outcomes. This is a local artifact for the fix agent's
  own use and for post-run analytics (extracted by watcher).
  The review agent's plan compliance check (Phase 2.5) reads the plan
  from the `## Fix Plan (v* — APPROVED)` **Jira comment** (not from
  fix-plan.json), because the review runs in a separate sandbox and
  cannot access the fix agent's local files. The Jira comment is the
  cross-stage transport mechanism for plan data.
- **RTK token optimization** — validate RTK compatibility with OpenCode:
  - RTK is currently integrated via Claude Code hooks (`rtk init`,
    `rtk hooks uninstall`, `rtk gain`). OpenCode uses a different
    hook system (TypeScript plugins, 25+ lifecycle events).
  - Check if RTK already has an OpenCode integration (`rtk init`
    may auto-detect OpenCode). If not, options:
    a. Write an OpenCode plugin that wraps RTK's rewrite logic
    b. Use RTK as a PreToolUse hook (intercept bash commands)
    c. Check if OpenCode has native command output filtering
  - If RTK is not compatible with OpenCode in Phase 1, defer to
    Phase 3 (after sandboxing is in place). RTK is optional
    (RTK_ENABLED=false by default) — the pipeline works without it.
  - Update opencode.json to include RTK_ENABLED config if supported.
  - The fix agent skill's RTK sections (Phase 1 init, Phase 4B pause,
    Phase 10 metrics) need updating for OpenCode's hook mechanism.
- **Smart context validation** — verify these features carry over:
  - Signal classification (Phase 1 step 5) — LLM reasoning, no
    platform dependency. Transfers as-is.
  - Investigation strategies (investigation-strategies.md) — must be
    moved alongside the fix skill. Already in the mapping table.
  - Knowledge repo clone (Phase 2 step 6) — `git clone --depth 1`
    with hardened config. Works the same in OpenCode. Verify that
    OpenShell network policy allows cloning from knowledge repo hosts.
  - Multi-skill URLs (Phase 1 step 2) — fetched via `curl`. Works in
    any runtime. Verify skill URL allowlist is passed in dispatch prompt.
  - Complexity gate signal floors — skill logic, no platform dependency.

**What stays the same:**
- All skill logic (investigation, audit loop, review methodology)
- Security hardening (git, URL, sensitive files)
- Label state machine (Jira labels)
- Cross-workflow contracts (Jira comments)
- Signal-driven investigation (5 strategies)
- Knowledge repo support (clone + size check + cleanup)
- Multi-skill URL support (allowlist + fetch + max 5)

**Effort:** Medium — file moves + Ambient reference removal + MCP tool
name validation + RTK compatibility check. The 1,020-line issue-fix.md
is the dominant cost center.

**Done when:**
- `opencode run --skill issue-fix` executes without errors on a test repo
- MCP tools (mcp-atlassian) are callable from within OpenCode
- Audit sub-agents spawn and return structured JSON
- AGENTS.md rules are loaded in context (verify via agent output)
- Signal classification produces correct signal type for test tickets
- Investigation strategies file is loadable from the skill
- RTK status determined: compatible / needs plugin / deferred

### Phase 2: Build Watcher as External Script (1-2 weeks)

**What:**
- Python script (~200 lines) that queries Jira (REST API) for `autofix`
  tickets
- Dispatches `opencode run` per ticket via subprocess
- Manages label state machine (same logic as current watcher)
- Enforces concurrency limits (MAX_CONCURRENT_FIX_SESSIONS=4,
  MAX_CONCURRENT_REVIEW_SESSIONS=2, MAX_CONCURRENT_REVIEW_FIX_SESSIONS=2)
- Wraps each invocation with `timeout` command as backstop
- Runs as a cron job (or K8s CronJob)

This replaces the Ambient watcher session. The script uses direct Jira
REST API (no MCP needed for the watcher).

**Done when:**
- Watcher polls Jira, identifies `autofix` tickets correctly
- Dispatches `opencode run` and the fix agent completes one ticket
- Concurrency limits prevent over-dispatch
- Stale session cleanup detects orphaned processes

### Phase 3: Add OpenShell Sandboxing (2-3 weeks)

**What:**
- Define OpenShell policies per agent role (fix, review, review-fix)
- Watcher script creates sandboxes: `openshell sandbox create -- opencode run ...`
- Test sandbox isolation (filesystem, network)
- Design sandbox failure recovery (watcher detects crashed sandboxes)
- Verify Landlock enforcement on target kernel (`/sys/kernel/security/landlock/abi_version`)
- Measure sandbox creation latency (target: < 60s including image pull)
- Create a local dev wrapper script for testing policies on developer
  laptops: `./scripts/local-sandbox-test.sh fix` that runs
  `openshell sandbox create --driver docker -- opencode run ...` with
  the same policies used in OpenShift. This lets developers validate
  Landlock policies locally before deploying to the cluster.

**Done when:**
- 4 fix + 2 review + 2 review-fix sandboxes run concurrently for 3 cycles
- Sandbox network policy blocks unauthorized hosts
- Sandbox creation latency < 60s measured
- Sandbox crash recovery works (watcher detects and cleans up)

Note: OpenShell is alpha (v0.0.36). Pin to a specific version. Do not
upgrade mid-migration. If APIs change, only the watcher dispatch layer
needs updating — skill files are unaffected.

### Phase 4: Test End-to-End on OBSINTA (2 weeks)

**What:**
- Run the full pipeline on staging tickets
- Validate: ticket → fix → review → review-fix → merge
- Collect data: fix quality, costs, failure modes
- First 3-5 days: happy path on 3-5 tickets
- Remaining days: failure scenarios, edge cases, retry/cancel flows

**Done when:**
- 10 tickets processed with zero sandbox failures
- Full pipeline completes at least 3 tickets end-to-end
- Monitoring captures all key metrics (if monitoring is in place)
- Label state machine works correctly across all transitions

**Total estimated timeline: 9-14 weeks** (including model evaluation)

| Phase | Duration | Cumulative |
|-------|----------|-----------|
| Phase 0: Observability | 1 week | 1 week |
| Phase 1: Skill translation | 1-2 weeks | 2-3 weeks |
| Phase 2: Watcher script | 1-2 weeks | 3-5 weeks |
| Phase 3: OpenShell sandboxing | 2-3 weeks | 5-8 weeks |
| Phase 4: E2E testing on OBSINTA (Claude) | 2 weeks | 7-10 weeks |
| Phase 5: Free model evaluation | 2-3 weeks | 9-13 weeks |
| Buffer for unknowns | 1 week | 10-14 weeks |

### Phase 5: Free/Open Model Evaluation (2-3 weeks)

**Why:** Claude Opus costs $15/MTok input, $75/MTok output. At scale,
model cost dominates. Free/open models could reduce per-ticket cost to
near-zero for some pipeline stages. But quality trade-offs must be
measured, not assumed.

**What:**
Run the same 10-20 OBSINTA tickets through both Claude and free models.
Compare results using run-metadata.json data.

**Model candidates:**

| Provider | Model | Cost | Best for |
|----------|-------|------|----------|
| Ollama (local) | Qwen3 72B | Free (self-hosted GPU) | Fix agent, review-fix |
| Ollama (local) | Qwen3 30B | Free (runs on 16GB RAM) | Audit sub-agents |
| Groq (cloud) | Llama 3.3 70B | Free tier (rate limited) | Review agent, audit |
| Anthropic | Claude Opus | $$$ | Baseline comparison |
| Anthropic | Claude Sonnet | $$ | Baseline comparison |

**Evaluation matrix per ticket:**

| Metric | Measure | Source |
|--------|---------|--------|
| Fix quality | Did it find the correct root cause? Same fix? | Manual comparison of PRs |
| Review quality | Same findings? False positive rate? | Compare review comments |
| Audit quality | Useful plan feedback or hallucinated findings? | Compare audit iterations |
| Success rate | bot-merged vs bot-fix-failed | run-metadata.json outcome |
| Duration | Wall-clock time per stage | run-metadata.json timestamps |
| Token usage | Input/output tokens per run | run-metadata.json (if available) |
| Cost | $ per ticket (Claude) vs $0 (free) | Calculated from tokens |

**Evaluation approach:**
1. Week 1: run 10 tickets on Claude (baseline) — collect run-metadata
2. Week 2: run same 10 tickets on free model — same repo state, same
   ticket descriptions
3. Week 3: compare results, identify which stages degrade, which are
   equivalent

**Tiered rollout based on results:**

| If free model... | Then... |
|-----------------|---------|
| Matches Claude on audit sub-agents | Move audit to free (lowest risk, 3 sub-agents per ticket) |
| Matches Claude on review | Move review to free (read-only, bounded task) |
| Close to Claude on fix | Consider for simple fixes (AUDIT_SKIP_SIMPLE tickets) |
| Degrades on fix | Keep fix on Claude, free model for everything else |
| Degrades on everything | Stay Claude-only, re-evaluate with next model generation |

**OpenCode config for A/B testing:**
```json
{
  "provider": {
    "anthropic": {},
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://ollama-service:11434/v1" },
      "models": {
        "qwen3:72b": { "tools": true },
        "qwen3:30b": { "tools": true }
      }
    },
    "groq": {}
  }
}
```

Switch models per agent by changing the `model:` field in agent
definitions — no code changes needed.

**Infrastructure for local models:**
- Ollama or vLLM deployed as a K8s Deployment in the OpenShift cluster
- GPU node(s) for 72B models (requires NVIDIA GPU operator)
- For 30B models: CPU-only nodes with 32GB+ RAM (slower but functional)
- Groq: cloud API, no infrastructure needed (free tier has rate limits)

**Done when:**
- 10+ tickets compared between Claude and free model
- Per-stage quality scores documented
- Cost savings quantified ($ per ticket reduction)
- Decision made: which stages move to free, which stay Claude

## Target Deployment: OpenShift

The system targets an OpenShift cluster for production deployment:

**Watcher:**
- K8s CronJob (or Deployment with internal polling loop) in a dedicated
  namespace (e.g., `issue-fix-agent`)
- **Singleton requirement:** Only one watcher instance may dispatch runs
  or append to `runs.jsonl`. If deployed as a CronJob, set
  `concurrencyPolicy: Forbid`. If deployed as a Deployment, use exactly
  1 replica OR implement leader election. This prevents duplicate agent
  dispatch and PVC write races.
- ServiceAccount with minimal RBAC (no cluster-admin)
- Secrets via OpenShift Secrets (GITHUB_TOKEN, JIRA_API_TOKEN,
  JIRA_USERNAME, SLACK_WEBHOOK_URL)
- ConfigMap for config.env and projects.json values

**OpenShell Gateway:**
- Deployed as a Deployment + Service in the same namespace
- Compute driver: Kubernetes (creates sandbox pods in-cluster)
- Gateway port exposed as ClusterIP service (watcher → gateway)

**Sandbox Pods:**
- Created by OpenShell gateway per agent run
- Pod spec from OpenShell policies (CPU/memory limits, network policies)
- Container image pre-built with: OpenCode, mcp-atlassian, git, gh CLI
- Image stored in internal registry (quay.io or OpenShift internal)

**Observability:**
- `runs.jsonl` stored on a PersistentVolumeClaim (survives pod restarts)
- Alert script runs as a sidecar or periodic CronJob
- Slack webhook for alerts

**Container Image Requirements:**
- Base: UBI9 or similar Red Hat-supported base
- Pre-installed: `opencode`, `openshell`, `mcp-atlassian` (via uvx),
  `git`, `gh`, `curl`, `jq`, `bash`
- Size target: < 2GB
- Image pre-pull via DaemonSet to reduce sandbox startup latency

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

---

## Enterprise Governance

### Reviewer Independence

The review agent MUST run in a fresh, independent workspace — never as
a continuation of the fix agent's context. This is enforced by:
- Separate OpenShell sandbox per stage (fix sandbox ≠ review sandbox)
- Review sandbox clones the repo fresh and checks out the PR branch
  via `gh pr checkout` (read-only, no push credentials)
- Review agent uses a different model tier than the fix agent (Sonnet
  vs Opus) to get independent perspective
- Future: consider cross-provider review (different LLM vendor for
  review) as a quality governance mechanism

### Rollout / Rollback

**Staged rollout:**
1. Phase 4 testing on OBSINTA staging tickets (non-production)
2. Shadow mode (dry-run): run OpenCode pipeline on same tickets with
   DRY_RUN=true. Two enforcement points:
   - **Agent side**: PreToolUse hooks intercept and log (not execute)
     `git push`, `gh pr create`, and MCP Jira tool calls.
   - **Watcher side**: the watcher script itself checks DRY_RUN before
     any Jira REST call (label swaps, comments, transitions). In
     dry-run mode, the watcher logs the intended action but does not
     execute the HTTP request. This is critical because the watcher
     uses direct REST, not MCP — PreToolUse hooks do not cover it.
   The agent investigates and plans normally but does not create real
   PRs or modify Jira. Compare proposed fix against the human's fix.
   **Shadow mode deduplication:** Because Jira labels are not mutated
   in dry-run mode, the watcher MUST maintain a local cache (e.g.,
   `shadow-runs.json` on the PVC) of processed tickets (keyed by
   ticket ID + updated timestamp) to prevent infinite re-processing
   of the same ticket on every poll.
3. Pilot: 1 team, 1 Jira project, 5-10 tickets/week for 2 weeks
4. Expand: add projects to `watched_projects` in projects.json

**Rollback:**
- To stop all automation: remove the watcher CronJob/Deployment
- To stop one ticket: add `no-autofix` label
- To stop and retry: add `bot-cancelled` label
- To revert a merged fix: standard git revert on the target repo
- Watcher script has no persistent state — stopping and restarting
  it is safe (Jira labels are the source of truth)

**Kill switch:** delete the watcher Deployment/CronJob. All in-flight
sandboxes will expire at their TTL. Tickets in `bot-in-progress` will
be cleaned up by the watcher's stale session cleanup when it restarts
(or manually by removing the label).

### Ownership

| Component | Owner | Responsibilities |
|-----------|-------|-----------------|
| Watcher script | Platform team | Deployment, monitoring, cron schedule |
| Skill files | Agent team | Fix/review logic, investigation strategies |
| OpenShell policies | Security team | Filesystem/network/process rules |
| Jira project config | Project leads | watched_projects, allowlists |
| Container image | Platform team | Build, push, pre-pull |
| MCP servers | Platform team | mcp-atlassian deployment, credentials |
| Incident review | Agent team + project leads | Post-mortem on bot-fix-failed patterns |

### Artifact Retention

| Artifact | Location | Retention |
|----------|----------|-----------|
| `run-metadata.json` | Extracted to `runs/<run-id>/` on PVC | 90 days (configurable) |
| `.audit/approved-plan.md` | Extracted to `runs/<run-id>/` on PVC | 90 days. Also summarized in Jira `## Fix Plan` comment |
| `.audit/validation.json` | Extracted to `runs/<run-id>/` on PVC | 90 days. Also summarized in Jira `## Fix Applied` telemetry |
| `.audit/fix-plan.json` | Extracted to `runs/<run-id>/` on PVC | 90 days. Key fields also in `## Fix Plan` Jira comment |
| Jira comments | Jira | Permanent (follows Jira retention policy) |
| PR + commits | GitHub | Permanent (follows repo retention policy) |
| Watcher logs | `runs.jsonl` on PVC | 90 days |
| Sandbox logs | OpenShell gateway | Depends on gateway log retention config |

For audit compliance, the `runs.jsonl` file is the execution record of
truth. Jira comments are the business record. Both must be retained for
the compliance period. Consider exporting `runs.jsonl` to a central log
store (FluentBit → Splunk/ELK) for long-term retention beyond 90 days.
