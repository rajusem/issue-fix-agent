---
name: jira-watcher
description: "Polls Jira for autofix tickets and dispatches Ambient sessions.
  Runs as a short-lived cron session with 5 phases: new tickets, reviews,
  review-fixes, post-merge, and stale cleanup."
version: "1.0"
type: workflow
---

# Jira Watcher Skill

## Overview

This skill runs one complete polling cycle:
1. Pick up new `autofix` tickets → dispatch fix sessions
2. Pick up `bot-ready-for-review` tickets → dispatch review sessions
3. Pick up `bot-review-fix` tickets → dispatch review-fix sessions
4. Check for merged PRs → update Jira
5. Clean up stale sessions

After all phases, post a summary to Slack and exit.

## Configuration

Read `config/projects.json` for:
- `watched_projects` — Jira project keys to monitor
- `skill_url_allowlist` — trusted skill URL patterns
- `bot_service_account` — service account to assign tickets to

Read `config/config.env` for TTLs, models, and concurrency limits.

## Phase 1: New Autofix Tickets

### Query
```
JQL: labels = autofix AND labels NOT IN (bot-in-progress, bot-ready-for-review, bot-review-complete, bot-review-fix, bot-merged, bot-fix-failed, bot-missing-info) AND project IN (<WATCHED_PROJECTS>)
```

Use `mcp__atlassian__searchJiraIssuesUsingJql` with the JQL above.

### For each ticket:

1. **Parse description and comments** for agent configuration:
   - `**Repository**:` (REQUIRED)
   - `**Branch**:` (optional)
   - `**Commit**:` (optional)
   - `**Skill**:` (optional)

2. **If Repository URL missing**:
   - Add `bot-missing-info` label using `mcp__atlassian__editJiraIssue`
     (prevents re-picking this ticket on subsequent cycles)
   - Add Jira comment:
     ```
     ## Missing Information
     The following mandatory fields are needed for the agent to work on this ticket:
     - **Repository**: URL of the repository to fix (e.g., https://github.com/org/repo)

     Optional fields that help the agent:
     - **Branch**: Target branch (defaults to repo's default branch)
     - **Commit**: Specific commit SHA to investigate
     - **Skill**: URL to domain-specific guidance (must be from an allowed source)

     Please add these to the ticket description or as a comment, then
     remove the `bot-missing-info` label to trigger the agent.
     ```
   - Skip this ticket.

3. **Check for existing active session**:
   - Query Ambient sessions with label `jira-ticket=<TICKET-KEY>`
   - If an active (non-terminal) session exists, skip this ticket.

4. **Check concurrency limits**:
   - Count active fix sessions (label `type=issue-fix` in non-terminal phases)
   - If at `MAX_CONCURRENT_FIX_SESSIONS`, skip remaining tickets.

5. **Add `bot-in-progress` label** using `mcp__atlassian__editJiraIssue`
   (state guard — do this BEFORE creating session)

6. **Assign bot service account** to the ticket

7. **Attempt Jira status transition** to "In Progress":
   - Use `mcp__atlassian__transitionJiraIssue` if available
   - If transition fails due to missing gate fields (Sprint, Story Points, etc.),
     skip the transition and proceed with label-only tracking
   - Add Jira comment noting if transition was skipped

8. **Create fix session** via Ambient `create_session` MCP.
   Include the ticket key, parsed config fields, AND the skill URL
   allowlist from `config/projects.json` in the prompt so the fix agent
   has all context without needing access to the watcher's config files:
   ```json
   {
     "prompt": "Fix the issue described in Jira ticket <TICKET-KEY>. Follow the issue-fix skill.\n\nTicket: <TICKET-KEY>\nRepository: <repo_url>\nBranch: <branch>\nCommit: <commit_sha or 'none'>\nSkill URL: <skill_url or 'none'>\nSkill URL Allowlist: <comma-separated patterns from projects.json>\nRTK_ENABLED: <RTK_ENABLED from config.env, default false>",
     "name": "fix-<ticket-key-lower>",
     "labels": {
       "jira-ticket": "<TICKET-KEY>",
       "type": "issue-fix"
     },
     "model": "<FIX_MODEL>",
     "repos": [{"url": "<repo_url>", "branch": "<branch>", "autoPush": true}],
     "timeout": "<FIX_SESSION_TTL * 60>"
   }
   ```

9. **Add Jira comment** with session link:
   ```
   ## Agent Session Started
   **Session**: [fix-<ticket-key>](<session_url>)
   **Model**: <model>
   **Started**: <timestamp>
   ```

## Phase 2: Review Dispatch

### Query
```
JQL: labels = bot-ready-for-review AND labels NOT IN (bot-review-complete, bot-review-fix) AND project IN (<WATCHED_PROJECTS>)
```

### For each ticket:

1. Read Jira ticket comments to extract the PR repo (from the fix agent's `## Fix Applied` comment)
2. Check for existing active review session (label `jira-ticket=<KEY>`, `type=issue-review`)
3. Check concurrency limits (`MAX_CONCURRENT_REVIEW_SESSIONS`)
4. Create review session:
   ```json
   {
     "prompt": "Review the PR for Jira ticket <TICKET-KEY>. Follow the issue-review skill.",
     "name": "review-<ticket-key-lower>",
     "labels": {
       "jira-ticket": "<TICKET-KEY>",
       "type": "issue-review"
     },
     "model": "<REVIEW_MODEL>",
     "repos": [{"url": "<repo_url_from_pr>", "branch": "<pr_head_branch>"}],
     "timeout": "<REVIEW_SESSION_TTL * 60>"
   }
   ```
5. Add Jira comment with review session link.

## Phase 3: Review-Fix Dispatch

### Query
```
JQL: labels = bot-review-fix AND labels NOT IN (bot-ready-for-review, bot-fix-failed) AND project IN (<WATCHED_PROJECTS>)
```

### For each ticket:

1. **Check review-fix cycle count**:
   - Count Jira comments with `## Review-Fix Cycle` prefix
   - If count >= `REVIEW_FIX_MAX_CYCLES` (default 3):
     - Atomic swap using `mcp__atlassian__editJiraIssue`:
       `bot-review-fix` → `bot-fix-failed`
     - Add comment: "Max review cycles exceeded — needs human attention."
     - Skip this ticket.

2. Read Jira ticket comments to extract the PR repo (from the fix agent's `## Fix Applied` comment)
3. Check for existing active review-fix session
4. Check concurrency limits (`MAX_CONCURRENT_REVIEW_FIX_SESSIONS`)
5. Create review-fix session:
   ```json
   {
     "prompt": "Address review findings for Jira ticket <TICKET-KEY>. Follow the review-fix skill. This is cycle <N>.",
     "name": "reviewfix-<ticket-key-lower>-c<N>-<timestamp>",
     "labels": {
       "jira-ticket": "<TICKET-KEY>",
       "type": "review-fix",
       "review-cycle": "<N>"
     },
     "model": "<REVIEW_FIX_MODEL>",
     "repos": [{"url": "<repo_url_from_pr>", "branch": "<pr_head_branch>", "autoPush": true}],
     "timeout": "<REVIEW_FIX_SESSION_TTL * 60>"
   }
   ```
6. Add Jira comment with session link.

## Phase 4: Post-Merge Updates

1. Query Jira for tickets with `bot-review-complete` label:
   ```
   JQL: labels = bot-review-complete AND project IN (<WATCHED_PROJECTS>)
   ```
2. For each ticket, extract the PR URL and repo from the `## Fix Applied`
   comment in ticket comments.
3. Check if the PR is merged:
   ```bash
   gh pr view <number> --repo <owner/repo> --json state,merged,mergedAt,mergedBy,mergeCommit
   ```

4. For each merged PR:
   a. Atomic label swap using `mcp__atlassian__editJiraIssue`:
      remove `bot-review-complete`, add `bot-merged`
   d. Add Jira comment:
      ```
      ## PR Merged
      **PR**: [#N](<pr_url>) merged to <base_branch>
      **Merge Commit**: <sha>
      **Merged By**: @<username>

      Ticket is ready for manual review and close.
      ```

## Phase 5: Stale Session Cleanup

1. Query Ambient for sessions with label `type=issue-fix` OR `type=review-fix`
   OR `type=issue-review` in terminal phases (Completed, Failed, Stopped).

2. For each terminal session:
   a. Extract `jira-ticket` label to get the ticket key
   b. Check if the Jira ticket still has `bot-in-progress`, `bot-review-fix`,
      or `bot-ready-for-review` (for stale review sessions)
   c. If yes — the session ended without updating Jira:
      - For `bot-in-progress` or `bot-review-fix`: atomic label swap to
        `bot-fix-failed` using `mcp__atlassian__editJiraIssue`
      - For `bot-ready-for-review` (stale review): leave label in place
        so the watcher re-dispatches a new review session on next cycle
      - Add comment: "Agent session ended without completing. Session: <link>. Status: <phase>."

## Cycle Summary

After all phases, post a summary to Slack (if `SLACK_WEBHOOK_URL` is configured):

```
Issue Fix Agent — Watcher Cycle Summary
- New tickets processed: N
- Missing info (awaiting user): N
- Fix sessions dispatched: N
- Review sessions dispatched: N
- Review-fix sessions dispatched: N
- Merged PRs updated: N
- Stale sessions cleaned: N
- Errors: N
```

Then exit the session.
