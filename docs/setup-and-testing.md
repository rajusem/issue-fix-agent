# Setup & Testing Guide

Step-by-step guide to configure and test the Issue Fix Agent system.

## Test Environment

| Component | Value |
|-----------|-------|
| Jira Site | `stage-redhat.atlassian.net` |
| Jira Project | `OBSINTA` |
| Test Repo | `https://github.com/rajusem/multicluster-observability-operator` |
| Platform | Ambient Platform (access + project ready) |

---

## Part 1: Prerequisites Setup

### 1.1 Jira API Token (for REST API fallback)

If `mcp-atlassian` MCP doesn't support all label operations, we need
a fallback. Get your Jira API token:

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Name: `issue-fix-agent`
4. Copy the token — you'll set it as `JIRA_API_TOKEN` in Ambient

Your `JIRA_USERNAME` is your Atlassian email address.

### 1.2 GitHub Token

Option A — Personal Access Token (for testing):
1. Go to https://github.com/settings/tokens
2. "Generate new token (classic)"
3. Scopes: `repo` (full), `workflow`
4. Copy token — set as `GITHUB_TOKEN` in Ambient

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

Before anything else, verify you can access Jira from an Ambient session.
Create a quick test session in Ambient and run:

```
Use mcp__atlassian__searchJiraIssuesUsingJql to search:
JQL: project = OBSINTA AND type = Bug ORDER BY created DESC
Return first 3 results.
```

**Expected**: Returns Jira issues from OBSINTA project.

If this fails, check your Ambient project's MCP server configuration for
`mcp-atlassian`.

---

## Part 2: MCP Tool Inventory Verification

This is the **critical prerequisite** from the plan. We need to verify
which Jira operations are available via MCP before testing workflows.

### 2.1 Test Each MCP Operation

Create an Ambient session and test each operation. Record which ones work.

#### Test 1: Search Issues (JQL)
```
Use mcp__atlassian__searchJiraIssuesUsingJql:
  JQL: project = OBSINTA ORDER BY created DESC
  maxResults: 3
```
Expected: Returns issue list. Record the key of the first issue for tests below.

#### Test 2: Get Issue Details
```
Use mcp__atlassian__getJiraIssue:
  issueIdOrKey: <issue-key-from-test-1>
```
Expected: Returns full issue details (summary, description, labels, status).

#### Test 3: Add Label
```
Use mcp__atlassian__editJiraIssue (or equivalent):
  issueIdOrKey: <issue-key>
  Add label: "test-bot-label"
```
Expected: Label added. Verify in Jira UI.

**If this tool doesn't exist**, try:
- `mcp__atlassian__updateJiraIssue`
- `mcp__atlassian__updateIssue`
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
Use mcp__atlassian__addCommentToJiraIssue (or equivalent):
  issueIdOrKey: <issue-key>
  body: "Test comment from issue-fix-agent setup"
```
Expected: Comment appears on the issue.

Record the actual tool name: `________________`

#### Test 6: Get Transitions
```
Use mcp__atlassian__getTransitionsForJiraIssue:
  issueIdOrKey: <issue-key>
```
Expected: Returns available transitions (e.g., "In Progress", "Done").

#### Test 7: Transition Issue
```
Use mcp__atlassian__transitionJiraIssue:
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
| JQL Search | `mcp__atlassian__searchJiraIssuesUsingJql` | | |
| Get Issue | `mcp__atlassian__getJiraIssue` | | |
| Add/Remove Labels | | | |
| Add Comment | | | |
| Get Transitions | `mcp__atlassian__getTransitionsForJiraIssue` | | |
| Transition Issue | `mcp__atlassian__transitionJiraIssue` | | |

**If any tool names differ from what's in the skill files**, update the
skill files before proceeding to testing.

---

## Part 3: Ambient Project Configuration

### 3.1 Environment Variables

Set these in your Ambient ProjectSettings CR or per-session:

```yaml
environmentVariables:
  JIRA_SITE: "stage-redhat.atlassian.net"
  GITHUB_TOKEN: "<your-github-token>"
  JIRA_USERNAME: "<your-atlassian-email>"
  JIRA_API_TOKEN: "<your-jira-api-token>"
  SLACK_WEBHOOK_URL: "<your-slack-webhook>"  # optional
```

### 3.2 MCP Servers

Ensure these MCP servers are configured in your Ambient project:

- `mcp-atlassian` — for Jira operations
- `session` — for spawning child sessions (built-in to Ambient)

### 3.3 Update Config Files

Edit `config/projects.json`:
```json
{
  "watched_projects": ["OBSINTA"],
  "skill_url_allowlist": [
    "https://raw.githubusercontent.com/rajusem/*/main/.claude/skills/*"
  ],
  "bot_service_account": "<your-bot-account-or-your-username>"
}
```

Edit `config/config.env`:
```
JIRA_SITE=stage-redhat.atlassian.net
JIRA_PROJECTS=OBSINTA
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

2. Create an Ambient session manually with this prompt:
   ```
   You are testing the jira-watcher skill in DRY RUN mode.

   Read the jira-watcher skill from workflows/jira-watcher/skills/jira-watcher.md.
   Execute ONLY Phase 1 (New Autofix Tickets) but DO NOT create any
   child sessions and DO NOT add any labels to tickets.

   Instead, for each ticket found, report:
   - Ticket key and summary
   - Whether Repository URL was found
   - Whether the ticket would pass pre-screening
   - What session would be created (name, model, repos)

   Use project OBSINTA on stage-redhat.atlassian.net.
   ```

3. Point the session to this repo for workflow files:
   ```json
   {
     "repos": [{"url": "https://github.com/<your-fork>/issue-fix-agent"}]
   }
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
3. Create an Ambient session with this prompt:
   ```
   You are the issue-fix agent for Jira ticket OBSINTA-<NUMBER>.
   Follow the issue-fix skill in workflows/issue-fix/skills/issue-fix.md.

   Jira Site: stage-redhat.atlassian.net
   Ticket: OBSINTA-<NUMBER>
   Repository: https://github.com/rajusem/multicluster-observability-operator
   Branch: main
   Commit: none
   Skill URL: none
   Skill URL Allowlist: (none configured)
   ```

4. Session config:
   ```json
   {
     "repos": [
       {"url": "https://github.com/rajusem/multicluster-observability-operator", "branch": "main", "autoPush": true}
     ],
     "model": "claude-opus-4-6"
   }
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
2. Create an Ambient session:
   ```
   You are the issue-review agent for Jira ticket OBSINTA-<NUMBER>.
   Follow the issue-review skill in workflows/issue-review/skills/issue-review.md.

   Jira Site: stage-redhat.atlassian.net
   Ticket: OBSINTA-<NUMBER>
   ```

3. Session config:
   ```json
   {
     "repos": [
       {"url": "https://github.com/rajusem/multicluster-observability-operator", "branch": "main"}
     ],
     "model": "claude-sonnet-4-6"
   }
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
1. Create an Ambient session:
   ```
   You are the review-fix agent for Jira ticket OBSINTA-<NUMBER>.
   Follow the review-fix skill in workflows/review-fix/skills/review-fix.md.
   This is cycle 1.

   Jira Site: stage-redhat.atlassian.net
   Ticket: OBSINTA-<NUMBER>
   ```

2. Session config:
   ```json
   {
     "repos": [
       {"url": "https://github.com/rajusem/multicluster-observability-operator",
        "branch": "<pr-branch-name>", "autoPush": true}
     ],
     "model": "claude-opus-4-6"
   }
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
2. Run the full watcher skill (all 5 phases)
3. Monitor the dispatched fix session
4. Wait for the fix → review → (optional review-fix) → review-complete cycle

**Expected**: The full pipeline runs without manual intervention.

---

## Part 5: Troubleshooting

### Common Issues

| Problem | Check | Fix |
|---------|-------|-----|
| Watcher finds no tickets | JQL query correct? Project key matches? | Verify labels on ticket, check `watched_projects` in config |
| MCP tool not found | Tool name correct? | Run `mcp__atlassian__` prefix and check available tools |
| Label update fails | MCP supports label ops? | Switch to curl fallback (see skill files for syntax) |
| Fix agent can't clone repo | GITHUB_TOKEN set? Repo accessible? | Check token scopes, repo visibility |
| PR creation fails | `gh` CLI authenticated? | Run `gh auth status` in session |
| Jira transition fails | Gate fields missing? | Expected — skill skips transition gracefully |
| Session times out | TTL too short? | Increase in `config.env` |
| Comment spamming | `bot-missing-info` label not added? | Check JQL exclusion list |

### Checking Session Logs

In Ambient, view session logs at:
```
<AMBIENT_URL>/projects/<PROJECT>/sessions/<SESSION-NAME>
```

### Cleanup After Testing

1. Remove test labels from Jira tickets:
   - Remove all `bot-*` labels
   - Remove `autofix` if no longer needed
2. Close test PRs on GitHub
3. Delete test branches: `git push origin --delete <branch>`
4. Stop any running Ambient sessions

---

## Part 6: Production Readiness Checklist

Before running on real tickets:

- [ ] MCP tool inventory verified (Part 2) — all tools work or fallbacks confirmed
- [ ] All 7 tests passed
- [ ] `config/projects.json` updated with real project keys
- [ ] GitHub App configured (not PAT) for production repos
- [ ] Slack webhook configured for notifications
- [ ] Ambient cron schedule set up for watcher (recommended: every 20 min)
- [ ] Team briefed on label conventions (`autofix`, `bot-*` labels)
- [ ] Jira ticket template shared with team (Agent Configuration section)
- [ ] Concurrency limits reviewed in `config.env`
- [ ] TTLs reviewed (60 min fix, 30 min review, 45 min review-fix)
