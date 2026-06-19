# Setup & Testing Guide

> **Runtime:** OpenCode + OpenShell. See `docs/plan-opencode-openshell-migration.md`
> for the full migration plan. Parts 1-3 below have been updated for the
> OpenCode stack. Test scenarios (Parts 4, 7, 8) test Jira/GitHub behavior
> and remain valid regardless of runtime.

Step-by-step guide to configure and test the Issue Fix Agent system.

## Test Environment

| Component | Value |
|-----------|-------|
| Jira Site | `stage-redhat.atlassian.net` |
| Jira Project | `OBSINTA` |
| Test Repo | `https://github.com/rajusem/multicluster-observability-operator` |
| Platform | OpenCode + OpenShell on OpenShift |

---

## Part 1: Prerequisites Setup

### 1.1 Jira API Token (for REST API fallback)

If `mcp-atlassian` MCP doesn't support all label operations, we need
a fallback. Get your Jira API token:

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Name: `issue-fix-agent`
4. Copy the token — set as `JIRA_API_TOKEN` environment variable

Your `JIRA_USERNAME` is your Atlassian email address.

### 1.2 GitHub Token

Option A — Personal Access Token (for testing):
1. Go to https://github.com/settings/tokens
2. "Generate new token (classic)"
3. Scopes: `repo` (full), `workflow`
4. Copy token — set as `GITHUB_TOKEN` environment variable

Option B — GitHub App (for production):
1. Create GitHub App with permissions: `contents: write`, `pull-requests: write`, `metadata: read`
2. Install on `rajusem/multicluster-observability-operator`
3. Generate installation token

### 1.3 Slack Webhook (optional)

1. Go to https://api.slack.com/apps → Create New App
2. Features → Incoming Webhooks → Activate
3. Add New Webhook to Workspace → select channel
4. Copy URL — set as `SLACK_WEBHOOK_URL`

### 1.4 Verify MCP-Atlassian Access

Before anything else, verify you can access Jira from OpenCode:

```bash
opencode run "Use atlassian_jira_search to search: JQL: project = OBSINTA AND type = Bug ORDER BY created DESC. Return first 3 results."
```

**Expected**: Returns Jira issues from OBSINTA project.

If this fails, check `opencode.json` MCP configuration and ensure
`JIRA_USERNAME` / `JIRA_API_TOKEN` are set in the environment.

---

## Part 2: MCP Tool Inventory Verification

This is the **critical prerequisite** from the plan. We need to verify
which Jira operations are available via MCP before testing workflows.

### 2.1 Test Each MCP Operation

Run OpenCode and test each operation. Record which ones work.

#### Test 1: Search Issues (JQL)
```
Use atlassian_jira_search:
  JQL: project = OBSINTA ORDER BY created DESC
  maxResults: 3
```
Expected: Returns issue list. Record the key of the first issue for tests below.

#### Test 2: Get Issue Details
```
Use atlassian_jira_get_issue:
  issueIdOrKey: <issue-key-from-test-1>
```
Expected: Returns full issue details (summary, description, labels, status).

#### Test 3: Add Label
```
Use atlassian_jira_update_issue (or equivalent):
  issueIdOrKey: <issue-key>
  Add label: "test-bot-label"
```
Expected: Label added. Verify in Jira UI.

**If this tool doesn't exist**, try:
- `atlassian_jira_update_issue`
- `atlassian_jira_update_issue`
- Direct REST API fallback (see below)

Record the actual tool name that works: `________________`

#### Test 4: Remove Label
```
Use the same tool as Test 3:
  Remove label: "test-bot-label"
```
Expected: Label removed.

#### Test 5: Add Comment
```
Use atlassian_jira_add_comment (or equivalent):
  issueIdOrKey: <issue-key>
  body: "Test comment from issue-fix-agent setup"
```
Expected: Comment appears on the issue.

Record the actual tool name: `________________`

#### Test 6: Get Transitions
```
Use atlassian_jira_get_transitions:
  issueIdOrKey: <issue-key>
```
Expected: Returns available transitions (e.g., "In Progress", "Done").

#### Test 7: Transition Issue
```
Use atlassian_jira_transition_issue:
  issueIdOrKey: <issue-key>
  transitionId: <id-from-test-6>
```
Expected: Issue status changes. (Transition back if needed.)

### 2.2 REST API Fallback Test

If label operations (Test 3/4) are not available via MCP, test the
curl-based fallback:

```bash
curl -s -X PUT "https://stage-redhat.atlassian.net/rest/api/3/issue/<KEY>" \
  -u "<your-email>:<api-token>" \
  -H "Content-Type: application/json" \
  -d '{"update":{"labels":[{"add":"test-bot-label"}]}}'
```

Then remove:
```bash
curl -s -X PUT "https://stage-redhat.atlassian.net/rest/api/3/issue/<KEY>" \
  -u "<your-email>:<api-token>" \
  -H "Content-Type: application/json" \
  -d '{"update":{"labels":[{"remove":"test-bot-label"}]}}'
```

### 2.3 Record Results

Fill in after testing:

| Operation | MCP Tool Name | Works? | Fallback Needed? |
|-----------|--------------|--------|-----------------|
| JQL Search | `atlassian_jira_search` | | |
| Get Issue | `atlassian_jira_get_issue` | | |
| Add/Remove Labels | | | |
| Add Comment | | | |
| Get Transitions | `atlassian_jira_get_transitions` | | |
| Transition Issue | `atlassian_jira_transition_issue` | | |

**If any tool names differ from what's in the skill files**, update the
skill files before proceeding to testing.

---

## Part 3: OpenCode Project Configuration

### 3.1 Environment Variables

Set these in the shell or via OpenShell `--env`:

```bash
export JIRA_SITE="stage-redhat.atlassian.net"
export GITHUB_TOKEN="<your-github-token>"
export JIRA_USERNAME="<your-atlassian-email>"
export JIRA_API_TOKEN="<your-jira-api-token>"
export ANTHROPIC_API_KEY="<your-anthropic-key>"
export SLACK_WEBHOOK_URL="<your-slack-webhook>"  # optional
```

### 3.2 MCP Servers

Configured in `opencode.json`:

- `atlassian` — mcp-atlassian for Jira operations (auto-started via `uvx`)

### 3.3 Update Config Files

Edit `config/projects.json`:
```json
{
  "watched_projects": ["OBSINTA"],
  "skill_url_allowlist": [
    "https://raw.githubusercontent.com/rajusem/*/main/.claude/skills/*"
  ],
  "knowledge_repo_allowlist": [],
  "allowed_repo_hosts": [
    "github.com"
  ],
  "bot_service_account": "<your-bot-account-or-your-username>"
}
```

`allowed_repo_hosts` is **required** — the watcher stops processing if
this field is missing or empty.

Edit `config/config.env`:
```
JIRA_SITE=stage-redhat.atlassian.net
```

---

## Part 4: Testing — Step by Step

### Test 1: Watcher Dry Run (No Dispatch)

**Goal**: Verify the watcher can query Jira and identify tickets without
actually dispatching sessions.

**Steps**:
1. Create a test Jira ticket in OBSINTA:
   - Type: Bug
   - Summary: "Test: Agent should fix this issue"
   - Description:
     ```
     The observability dashboard shows incorrect data when filtering
     by cluster name. Steps to reproduce: ...

     ---
     ## Agent Configuration
     **Repository**: https://github.com/rajusem/multicluster-observability-operator
     **Branch**: main
     ```
   - Labels: `autofix`

2. Run OpenCode in dry-run mode:
   ```bash
   opencode run "You are testing the jira-watcher in DRY RUN mode. \
     Read docs/reference/jira-watcher-spec.md. \
     Execute ONLY Phase 1 (New Autofix Tickets) but DO NOT create any \
     child sessions and DO NOT add any labels to tickets. \
     For each ticket found, report: ticket key, summary, whether repo URL \
     was found, whether it would pass pre-screening, what agent would be dispatched. \
     Use project OBSINTA on stage-redhat.atlassian.net."
   ```

**Expected**: The watcher finds your test ticket, reports it would pass
pre-screening, and shows the session it would create. No labels changed.

**Verify**: Check the Jira ticket — no `bot-` labels should be added.

### Test 2: Watcher Missing Info Handling

**Goal**: Verify the watcher handles missing Repository URL correctly.

**Steps**:
1. Create a Jira ticket in OBSINTA:
   - Summary: "Test: Missing repo info"
   - Description: "Something is broken. Please fix." (NO Agent Configuration section)
   - Labels: `autofix`

2. Run the watcher (same as Test 1 but NOT dry run — let it execute Phase 1)

**Expected**:
- Watcher adds `bot-missing-info` label to the ticket
- Watcher posts "## Missing Information" comment listing required fields
- Ticket is NOT picked up on subsequent watcher runs (excluded by JQL)

**Verify**:
- Check Jira: ticket has `bot-missing-info` label and the comment
- Run watcher again — it should NOT process this ticket

### Test 3: Fix Agent (Manual Session)

**Goal**: Test the fix agent in isolation before wiring it through the watcher.

**Steps**:
1. Use the test ticket from Test 1 (with repo URL in description)
2. Manually add `bot-in-progress` label to the ticket
3. Run the fix agent:
   ```bash
   opencode run --agent fix "Fix Jira ticket OBSINTA-<NUMBER>. \
     Jira Site: stage-redhat.atlassian.net \
     Repository: https://github.com/rajusem/multicluster-observability-operator \
     Branch: main"
   ```

**Expected** (depends on ticket content):
- Agent reads the Jira ticket
- Posts milestone comments (started, branch created, RCA, tests)
- Creates a branch and attempts a fix
- Creates a PR with Jira link in body
- Swaps labels: `bot-in-progress` → `bot-ready-for-review`
- Posts `## Fix Applied` comment with PR details

**OR if the issue can't be fixed**:
- Swaps labels: `bot-in-progress` → `bot-fix-failed`
- Posts `## Fix Failed` comment explaining why

**Verify**:
- Check Jira: labels changed, milestone comments posted
- Check GitHub: branch created, PR opened (if fix succeeded)

### Test 4: Review Agent (Manual Session)

**Goal**: Test the review agent on the PR created in Test 3.

**Prerequisite**: Test 3 succeeded and created a PR.

**Steps**:
1. Verify the ticket has `bot-ready-for-review` label
2. Run the review agent:
   ```bash
   opencode run --agent review "Review PR for Jira ticket OBSINTA-<NUMBER>. \
     Jira Site: stage-redhat.atlassian.net"
   ```

**Expected**:
- Agent fetches PR URL from Jira comments
- Reviews the diff through 3 lenses (correctness, security, quality)
- Posts review comment on PR (with findings or `READY_FOR_HUMAN_REVIEW`)
- Updates Jira:
  - If findings: swaps to `bot-review-fix`, posts review details
  - If clean: swaps to `bot-review-complete`, posts review summary

**Verify**:
- Check GitHub PR: review comment posted
- Check Jira: label changed, review summary comment posted

### Test 5: Review-Fix Agent (Manual Session)

**Goal**: Test the review-fix cycle (only if Test 4 found issues).

**Prerequisite**: Test 4 set `bot-review-fix` label.

**Steps**:
1. Run the review-fix agent:
   ```bash
   opencode run --agent review-fix "Address review findings for \
     Jira ticket OBSINTA-<NUMBER>. This is cycle 1. \
     Jira Site: stage-redhat.atlassian.net"
   ```

**Expected**:
- Agent reads review findings from PR comments
- Addresses CRITICAL/MAJOR findings
- Commits and pushes to the same branch
- Swaps labels: `bot-review-fix` → `bot-ready-for-review`
- Posts `## Review-Fix Cycle 1/3` comment

**Verify**:
- Check GitHub PR: new commits addressing review findings
- Check Jira: label changed to `bot-ready-for-review`, cycle comment posted

### Test 6: Post-Merge Update (Manual)

**Goal**: Test the post-merge Jira update flow.

**Prerequisite**: A PR exists with `bot-review-complete` label on the ticket.

**Steps**:
1. Manually approve and merge the PR on GitHub
2. Run the watcher (or just Phase 4) to detect the merge:
   ```
   Execute ONLY Phase 4 (Post-Merge Updates) of the jira-watcher skill.
   Check tickets with bot-review-complete label for merged PRs.
   ```

**Expected**:
- Watcher detects the merged PR
- Swaps labels: `bot-review-complete` → `bot-merged`
- Posts `## PR Merged` comment with merge commit, author

**Verify**:
- Check Jira: `bot-merged` label, merge details comment

### Test 7: Full Watcher Integration

**Goal**: Test the complete watcher cycle dispatching real sessions.

**Steps**:
1. Create a fresh test ticket with `autofix` label and repo URL
2. Run the full watcher skill (all 8 phases)
3. Monitor the dispatched fix session
4. Wait for the fix → review → (optional review-fix) → review-complete cycle

**Expected**: The full pipeline runs without manual intervention.

---

## Part 5: Troubleshooting

### Common Issues

| Problem | Check | Fix |
|---------|-------|-----|
| Watcher finds no tickets | JQL query correct? Project key matches? | Verify labels on ticket, check `watched_projects` in config |
| MCP tool not found | Tool name correct? | Run `atlassian_jira_` prefix and check available tools |
| Label update fails | MCP supports label ops? | Switch to curl fallback (see skill files for syntax) |
| Fix agent can't clone repo | GITHUB_TOKEN set? Repo accessible? | Check token scopes, repo visibility |
| PR creation fails | `gh` CLI authenticated? | Run `gh auth status` in session |
| Jira transition fails | Gate fields missing? | Expected — skill skips transition gracefully |
| Session times out | TTL too short? | Increase in `config.env` |
| Comment spamming | `bot-missing-info` label not added? | Check JQL exclusion list |

### Cleanup After Testing

1. Remove test labels from Jira tickets:
   - Remove all `bot-*` labels
   - Remove `autofix` if no longer needed
2. Close test PRs on GitHub
3. Delete test branches: `git push origin --delete <branch>`

---

## Part 6: Production Readiness Checklist

Before running on real tickets:

- [ ] MCP tool inventory verified (Part 2) — all tools work or fallbacks confirmed
- [ ] All tests passed (Parts 4, 7, and 8)
- [ ] `config/projects.json` updated with real project keys
- [ ] `allowed_repo_hosts` configured in `config/projects.json` (required)
- [ ] GitHub App configured (not PAT) for production repos
- [ ] Slack webhook configured for notifications
- [ ] Watcher cron schedule configured (recommended: every 20 min)
- [ ] Team briefed on label conventions (`autofix`, `bot-*`, `no-autofix`, `bot-retry`, `bot-cancelled`)
- [ ] Jira ticket template shared with team (Agent Configuration section)
- [ ] Concurrency limits reviewed in `config.env` (MAX_CONCURRENT_FIX_SESSIONS=4)
- [ ] TTLs reviewed (150 min fix, 30 min review, 45 min review-fix)
- [ ] Audit loop config reviewed (AUDIT_ENABLED, AUDIT_MAX_ITERATIONS,
      AUDIT_SKIP_SIMPLE, AUDIT_MODEL)

---

## Part 7: Audit Loop Test Scenarios

These test the design audit loop (Phase 4A + 4B) added to the fix
workflow. Run after verifying the basic fix pipeline (Part 4).

### Test 8: Simple Fix — Audit Skipped

1. Create a ticket with a 1-file, obvious fix (e.g., typo in a string)
2. Add `autofix` label
3. **Expected**: Fix agent writes plan, complexity gate routes to
   "skip audit", Jira shows `## Fix Plan (v1 — APPROVED, audit skipped)`
   with Planned Files list, proceeds directly to implementation
4. **Verify**: No `## Audit — Iteration` comments in Jira, fix
   completes faster than audit-enabled fixes (~30 min vs ~70 min)

### Test 9: Single Audit Iteration — Approved on First Pass

1. Create a ticket with a 3-5 file fix (medium complexity)
2. Add `autofix` label
3. **Expected**: Fix agent writes plan, complexity gate triggers audit,
   3 sub-agents run sequentially (Architecture, PE, Language Expert),
   no CRITICAL/MAJOR findings, plan approved on first iteration
4. **Verify**: Jira shows `## Audit — Iteration 1 Starting` heartbeat,
   followed by `## Fix Plan (vN — APPROVED)` with Planned Files

### Test 10: Two Audit Iterations — Revised and Approved

1. Create a ticket requiring a cross-module fix (5+ files, touching
   public interfaces)
2. Add `autofix` label
3. **Expected**: First iteration finds MAJOR issues, plan is revised,
   second iteration approves the revised plan
4. **Verify**: Jira shows two heartbeat comments, a revision comment
   (`## Fix Plan (v2 — Iteration 1 Revision)`), and final approval

### Test 11: Three Audit Iterations — Max Reached, Failed

1. Create a ticket with a fundamentally ambiguous fix (multiple valid
   approaches, unclear requirements)
2. Add `autofix` label
3. **Expected**: All 3 iterations produce MAJOR findings that can't
   converge, ticket marked `bot-fix-failed`
4. **Verify**: Jira shows 3 heartbeat comments, ticket has
   `bot-fix-failed` label, comment says "max iterations reached"

### Test 12: TTL Truncation

1. Create a complex ticket AND set a short FIX_SESSION_TTL (e.g., 60
   minutes in a test session) to force TTL pressure
2. Add `autofix` label
3. **Expected**: After Phase 4 RCA takes ~20-30 min, TTL checkpoint
   detects < 45 min remaining and skips audit loop
4. **Verify**: Jira comment says "Audit truncated — insufficient TTL"

### Test 13: Plan Compliance Check — Divergence Detected

1. Manually create a PR that adds files NOT in the approved plan
   (e.g., add unplanned config changes)
2. Trigger the review agent on the ticket
3. **Expected**: Phase 2.5 detects unplanned files. If > 50% unplanned,
   ticket marked `bot-fix-failed` with "Plan Compliance Failed"
4. **Verify**: Jira comment lists unplanned and missing files

### Test 14: Audit Disabled via Config

1. Set `AUDIT_ENABLED=false` in the session environment
2. Create a ticket with a complex fix (would normally trigger audit)
3. Add `autofix` label
4. **Expected**: Fix agent writes plan but skips audit entirely, Jira
   shows `## Fix Plan (v1 — APPROVED, audit disabled)`
5. **Verify**: No audit heartbeat comments, fix proceeds to
   implementation immediately

### Test 15: RTK Token Optimization

1. Ensure RTK binary is installed in the container image
2. Set `RTK_ENABLED=true` in the session environment
3. Create a ticket with a normal fix
4. Add `autofix` label
5. **Expected**: Phase 1 shows "RTK token optimization enabled (vX.Y.Z)",
   RTK hook intercepts shell commands, Phase 10 Jira comment includes
   `**RTK Token Savings**` table
6. **Verify**:
   - RTK healthcheck passed (no "WARNING: RTK healthcheck failed")
   - Token savings > 0% reported in Jira comment
   - If audit loop ran: RTK was paused during Phase 4B (no RTK
     filtering on evidence validation commands)
   - If any command shows >95% savings: canary warning in comment
7. **Negative test**: Set `RTK_ENABLED=false` (or unset). Verify NO
   RTK milestone, NO RTK savings in Jira comment, identical behavior
   to pre-RTK sessions

### Test 16: Regression Signal — Git History Investigation

1. Create a ticket with description: "The /api/users endpoint was
   returning correct results until last week. Now it returns 500."
2. Include `**Repository**:` pointing to a repo with recent commits
3. Add `autofix` label
4. **Expected**: Agent classifies signal as "regression", runs default
   investigation FIRST, then runs Git History Strategy (checks
   `git log`, `git blame` on affected files)
5. **Verify**: Fix plan includes `### Investigation Strategy` section
   with "Signals detected: regression" and git history findings

### Test 17: Multiple Skills + Knowledge Repo

1. Create a ticket with:
   ```
   **Repository**: https://github.com/org/backend
   **Skills**:
     - https://raw.githubusercontent.com/org/ai-helpers/main/.claude/skills/go.md
     - https://raw.githubusercontent.com/org/ai-helpers/main/.claude/skills/api.md
   **Knowledge Repo**: https://github.com/org/team-docs
   ```
2. Add `autofix` label
3. **Expected**: Agent fetches both skill URLs, clones knowledge repo
   to `.knowledge/`, references all during investigation
4. **Verify**:
   - Both skills fetched (check Jira milestone comments)
   - `.knowledge/` cloned with hooks disabled
   - `.knowledge/` cleaned up before Phase 5 implementation
   - Invalid/missing skill URLs logged as warnings, not errors

### Test 18: Concurrency Signal — Audit Floor

1. Create a ticket: "Intermittent 500 errors under load, cannot
   reproduce consistently"
2. Fix is a simple 1-file, 5-line change (would normally skip audit)
3. Add `autofix` label
4. **Expected**: Signal classified as "concurrency", complexity gate
   floors at single audit iteration minimum even though file/line
   count would normally skip audit
5. **Verify**: Audit runs despite simple fix (concurrency signal floor)

---

## Part 8: Label Lifecycle Test Scenarios

These test the label lifecycle features: cancellation, auto-recovery,
and retry.

### Test 19: Missing Info Auto-Recovery

**Goal**: Verify the watcher auto-detects added repo URL without manual
label removal.

1. Create a ticket with `autofix` label but NO repo URL in description
2. Run the watcher — ticket gets `bot-missing-info` label + comment
3. Add a valid repo URL to the ticket description (or as a plain comment
   — not starting with a `##` header, which the watcher skips)
4. Run the watcher again
5. **Expected**: Watcher Phase 7 detects the URL, removes `bot-missing-info`,
   posts "Repository URL detected. Ticket re-queued for processing."
6. Run watcher a third time — ticket is picked up by Phase 1 normally

### Test 20: Retry Failed Fix

**Goal**: Verify bot-retry triggers re-processing of a failed ticket.

**Prerequisite**: A ticket in `bot-fix-failed` state (from Test 3 failure
or manual label).

1. Add `bot-retry` label to the failed ticket
2. Run the watcher
3. **Expected**: Watcher Phase 8 removes `bot-fix-failed` + `bot-retry`,
   adds `bot-in-progress`, dispatches a new fix session with retry context
4. **Verify**: Fix agent reads prior `## Fix Failed` comments and uses
   them as negative constraints
5. **Verify**: After 3 total `## Fix Failed` comments (the watcher
   subtracts 1 for the initial attempt → 2 retries = MAX_FIX_RETRIES),
   watcher posts "Maximum retries (2) reached. This ticket needs human
   intervention." and removes `bot-retry` without dispatching a new session

### Test 21: Human Cancellation

**Goal**: Verify bot-cancelled stops active sessions and cleans up labels.

**Prerequisite**: A ticket in `bot-in-progress` state with an active
fix session.

1. Add `bot-cancelled` label to the ticket
2. Run the watcher
3. **Expected**: Watcher Phase 5 stops active sessions (or notes they
   will expire at TTL), removes `bot-cancelled`, `bot-in-progress`,
   `bot-ready-for-review`, `bot-review-fix`, `bot-review-complete`, and
   `bot-retry`, then adds `bot-fix-failed`. Posts `## Pipeline Cancelled`.
4. **Verify** (when `no-autofix` is NOT present): Comment offers retry
   (`bot-retry`) and opt-out (`no-autofix`)
5. **Edge case**: Add both `bot-cancelled` and `no-autofix` — verify
   comment says "Ticket is opted out of automation" without retry hint

### Test 22: Plan Approval Gate

**Goal**: Verify the human approval gate between audit and implementation.

**Prerequisites**: `PLAN_APPROVAL_REQUIRED=true` (default), a ticket
that triggers the audit loop.

1. Create a ticket with `autofix` label and a 3-5 file fix
2. Run the fix agent — it investigates, writes plan, runs audit
3. **Expected after audit approves**:
   - Jira shows `## Fix Plan (vN — APPROVED, awaiting human review)`
     with Root Cause, Approach, Planned Files, and Audit Trail sections
   - Ticket label swaps from `bot-in-progress` to `bot-plan-ready`
   - Agent session EXITS (does not proceed to implementation)
4. **Verify**: No PR created, no code changes, no `## Fix Applied`
5. Add `bot-proceed` label to the ticket
6. Run the watcher
7. **Expected**: Watcher Phase 1B picks up the ticket, swaps labels
   to `bot-in-progress`, dispatches new fix agent session
8. **Verify**: New session reads plan from Jira, implements fix,
   creates PR, swaps to `bot-ready-for-review`

**Rejection test**: Instead of step 5, add `bot-fix-failed` label.
Verify ticket moves to failed state. Add `bot-retry` to re-process.

**Timeout test**: Leave ticket in `bot-plan-ready` for >48h (or lower
`PLAN_APPROVAL_TIMEOUT_HOURS` for testing). Run watcher. Verify ticket
auto-fails with `## Plan Approval Timeout` comment.

**Gate disabled test**: Set `PLAN_APPROVAL_REQUIRED=false`. Create a
ticket. Verify agent proceeds directly from audit approval to
implementation without stopping at `bot-plan-ready`.
