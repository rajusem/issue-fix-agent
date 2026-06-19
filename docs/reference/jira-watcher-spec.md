---
name: jira-watcher
description: "Polls Jira for autofix tickets and dispatches Ambient sessions.
  Runs as a short-lived cron session with 8 phases: new tickets, reviews,
  review-fixes, post-merge, cancellation, stale cleanup, missing info
  re-check, and retry."
version: "1.1.0"
type: workflow
---

# Jira Watcher Skill

## Overview

This skill runs one complete polling cycle:
1. Pick up new `autofix` tickets → dispatch fix sessions
1B. Pick up `bot-plan-ready` + `bot-proceed` tickets → dispatch implementation sessions
2. Pick up `bot-ready-for-review` tickets → dispatch review sessions
3. Pick up `bot-review-fix` tickets → dispatch review-fix sessions
4. Check for merged/closed PRs → update Jira
5. Handle human cancellation (`bot-cancelled`)
6. Clean up stale sessions
7. Re-check `bot-missing-info` tickets for added information
8. Process retry requests (`bot-retry`)
9. Check for stale `bot-plan-ready` tickets (timeout)

After all phases, post a summary to Slack and exit.

## Configuration

Read `config/projects.json` for:
- `watched_projects` — Jira project keys to monitor
- `skill_url_allowlist` — trusted skill URL patterns
- `allowed_repo_hosts` — allowed repository hosts (e.g., `github.com`)
- `bot_service_account` — service account to assign tickets to

Read `config/config.env` for TTLs, models, and concurrency limits.

## TTL Awareness

Record the cycle start time at the beginning of the session:
```bash
CYCLE_START=$(date +%s)
```
Before **each phase** (including Phases 1-4), check remaining time:
```bash
WATCHER_TTL=${WATCHER_SESSION_TTL:-15}
ELAPSED=$(( $(date +%s) - CYCLE_START ))
REMAINING_MIN=$(( (WATCHER_TTL * 60 - ELAPSED) / 60 ))
```
If `REMAINING_MIN < 3`: skip remaining phases and proceed directly to
the Cycle Summary. Note skipped phases in the summary. This ensures the
Slack notification is always posted even if earlier phases ran long.

Within Phases 1-3, also check before each ticket iteration: if
`REMAINING_MIN < 5`, skip remaining tickets in the current phase and
move to the next phase.

## Label Swap Protocol

All label swaps use `atlassian_jira_update_issue` with both `remove` and
`add` in a single API call. After every label swap, verify the result:

1. Re-fetch the ticket via `atlassian_jira_get_issue`
2. Verify the old label is absent AND the new label is present
3. If inconsistent (old still present, or new missing):
   - Retry the swap once (wait 2 seconds before retry)
   - If still inconsistent after retry: add `bot-fix-failed` label and
     comment: "Label swap failed — ticket in inconsistent state. Expected
     to remove `<old>` and add `<new>`. Manual intervention needed."
4. If the verification `getJiraIssue` call itself fails (network error),
   log a warning and continue — do not enter `bot-fix-failed` for a
   transient verification failure.

This protocol applies to all label swaps in Phases 1-8.

## Phase 1: New Autofix Tickets

### Query
```
JQL: labels = autofix AND labels NOT IN (bot-in-progress, bot-ready-for-review, bot-review-complete, bot-review-fix, bot-merged, bot-fix-failed, bot-missing-info, no-autofix, bot-cancelled) AND project IN (<WATCHED_PROJECTS>)
```

Use `atlassian_jira_search` with the JQL above.

### For each ticket:

1. **Parse description and comments** for agent configuration:
   - `**Repository**:` (REQUIRED)
   - `**Branch**:` (optional)
   - `**Commit**:` (optional)
   - `**Skills**:` (optional — bulleted list of guidance URLs, max 5)
     Also accept `**Skill**:` (singular) for backward compatibility.
     Merge both into a single list, dedup by URL, cap at 5.
   - `**Knowledge Repo**:` (optional — separate repo for domain context)

2. **Validate Repository URL** (if found):
   The extracted repo URL must pass ALL checks:
   - Starts with `https://` (reject `http://`, `ssh://`, `file://`, `git://`,
     and scp-style `user@host:path`)
   - Host is in `allowed_repo_hosts` from `config/projects.json`
   - No credentials embedded in URL (no `user:pass@` or `token@` in authority)
   - No path traversal (`..` in path)
   - No query strings or fragments

   If `allowed_repo_hosts` is missing or empty in projects.json, this is a
   configuration error — log an error and skip ALL remaining tickets in this
   cycle. Post to Slack: "Watcher error: allowed_repo_hosts not configured."

   If the URL fails validation:
   - Add `bot-missing-info` label
   - Post comment: "## Missing Information\nRepository URL `<url>` failed
     validation: <specific reason>.\nAllowed hosts: <allowed_repo_hosts>.\n
     Please correct the URL in the ticket description or add a comment
     with the valid URL. The bot will detect it automatically."
   - Skip this ticket.

3. **If Repository URL missing** (not found in description or comments):
   - Add `bot-missing-info` label using `atlassian_jira_update_issue`
     (prevents re-picking this ticket on subsequent cycles)
   - Add Jira comment:
     ```
     ## Missing Information
     The following mandatory fields are needed for the agent to work on this ticket:
     - **Repository**: URL of the repository to fix (e.g., https://github.com/org/repo)

     Optional fields that help the agent:
     - **Branch**: Target branch (defaults to repo's default branch)
     - **Commit**: Specific commit SHA to investigate
     - **Skills**: URLs to domain-specific guidance (bulleted list, max 5)
     - **Knowledge Repo**: URL to a context repository (must be allowlisted)

     Please add these to the ticket description or as a comment.
     The bot will detect the information automatically and re-queue
     the ticket for processing.
     ```
   - Skip this ticket.

4. **Check for existing active session**:
   - Query Ambient sessions with label `jira-ticket=<TICKET-KEY>`
   - If an active (non-terminal) session exists, skip this ticket.

5. **Check concurrency limits**:
   - Count active fix sessions (label `type=issue-fix` in non-terminal phases)
   - If at `MAX_CONCURRENT_FIX_SESSIONS`, skip remaining tickets.

6. **Add `bot-in-progress` label** using `atlassian_jira_update_issue`
   (state guard — do this BEFORE creating session)

7. **Assign bot service account** to the ticket

8. **Attempt Jira status transition** to "In Progress":
   - Use `atlassian_jira_transition_issue` if available
   - If transition fails due to missing gate fields (Sprint, Story Points, etc.),
     skip the transition and proceed with label-only tracking
   - Add Jira comment noting if transition was skipped

9. **Create fix session** via Ambient `create_session` MCP.
   **If session creation fails:** immediately remove `bot-in-progress`
   label via `atlassian_jira_update_issue` (rollback step 5) and add
   a Jira comment: "Session creation failed — ticket returned to queue."
   Then skip to the next ticket.

   Include the ticket key, parsed config fields, all allowlists, and
   allowed repo hosts from `config/projects.json` in the prompt so the
   fix agent has all context without needing access to the watcher's
   config files. Knowledge Repo URL goes ONLY in the prompt text, NEVER
   in the `repos` array (the fix agent clones it manually with hardened
   git config):
   ```json
   {
     "prompt": "Fix the issue described in Jira ticket <TICKET-KEY>. Follow the issue-fix skill.\n\nTicket: <TICKET-KEY>\nRepository: <repo_url>\nBranch: <branch>\nCommit: <commit_sha or 'none'>\nSkill URLs: <comma-separated URLs or 'none'>\nSkill URL Allowlist: <comma-separated patterns from projects.json>\nAllowed Repo Hosts: <comma-separated from projects.json>\nKnowledge Repo: <url or 'none'>\nKnowledge Repo Allowlist: <comma-separated from projects.json>\nAUDIT_ENABLED: <AUDIT_ENABLED from config.env, default true>\nAUDIT_MAX_ITERATIONS: <AUDIT_MAX_ITERATIONS from config.env, default 3>\nAUDIT_SKIP_SIMPLE: <AUDIT_SKIP_SIMPLE from config.env, default true>\nAUDIT_MODEL: <AUDIT_MODEL from config.env, default claude-sonnet-4-6>\nRTK_ENABLED: <RTK_ENABLED from config.env, default false>",
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

10. **Add Jira comment** with session link:
    ```
    ## Agent Session Started
    **Session**: [fix-<ticket-key>](<session_url>)
    **Model**: <model>
    **Started**: <timestamp>
    ```

## Phase 1B: Plan Approval Dispatch

Handles tickets where the fix agent has completed investigation and
audit, posted the approved plan, and is waiting for human approval.
Only runs when `PLAN_APPROVAL_REQUIRED=true` (default).

### Query 1 — Approved plans ready to implement
```
JQL: labels = bot-plan-ready AND labels = bot-proceed AND labels NOT IN (bot-in-progress) AND project IN (<WATCHED_PROJECTS>)
```

### For each ticket:

1. Read Jira ticket comments to extract repo URL and branch from the
   original `## Agent Session Started` comment
2. Check concurrency limits (`MAX_CONCURRENT_FIX_SESSIONS`)
3. Remove labels: `bot-plan-ready`, `bot-proceed`
4. Add label: `bot-in-progress`
5. Dispatch fix agent session (implementation only):
   ```json
   {
     "prompt": "Resume from approved plan on <TICKET-KEY>. Read the ## Fix Plan comment with APPROVED in the header from Jira. Skip Phases 1-4. Start at Phase 5: Implement Fix. Jira Site: <JIRA_SITE>",
     "name": "fix-impl-<ticket-key-lower>",
     "labels": {
       "jira-ticket": "<TICKET-KEY>",
       "type": "issue-fix-impl"
     },
     "model": "<FIX_MODEL>",
     "repos": [{"url": "<repo_url>", "branch": "<branch>", "autoPush": true}],
     "timeout": "<FIX_SESSION_TTL * 60>"
   }
   ```
6. Add Jira comment:
   ```
   ## Agent Session Started (Implementation)
   **Session**: [fix-impl-<ticket-key>](<session_url>)
   **Model**: <model>
   **Started**: <timestamp>
   **Phase**: Implementing approved plan
   ```

### Query 2 — Stale unapproved plans (timeout)
```
JQL: labels = bot-plan-ready AND labels NOT IN (bot-proceed, bot-fix-failed, bot-in-progress) AND project IN (<WATCHED_PROJECTS>)
```

### For each ticket:

1. Read Jira comments, find the most recent `## Fix Plan` comment
   with `APPROVED` in the header
2. Parse the comment timestamp. If older than
   `PLAN_APPROVAL_TIMEOUT_HOURS` (default 48):
   - Remove label: `bot-plan-ready`
   - Add label: `bot-fix-failed`
   - Post comment:
     ```
     ## Plan Approval Timeout
     The approved plan has been waiting for human review for
     >PLAN_APPROVAL_TIMEOUT_HOURS hours without response.
     Marking as failed. To retry: add `bot-retry` label.
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
     - Atomic swap using `atlassian_jira_update_issue`:
       `bot-review-fix` → `bot-fix-failed`
     - Add comment: "Max review cycles exceeded — needs human attention.
       To retry the entire fix from scratch, add the `bot-retry` label."
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
   a. Atomic label swap (follow Label Swap Protocol):
      remove `bot-review-complete`, add `bot-merged`
   b. Add Jira comment:
      ```
      ## PR Merged
      **PR**: [#N](<pr_url>) merged to <base_branch>
      **Merge Commit**: <sha>
      **Merged By**: @<username>

      Ticket is ready for manual review and close.
      ```

5. For each PR that is CLOSED but NOT merged (state=CLOSED, merged=false):
   a. Atomic label swap (follow Label Swap Protocol):
      remove `bot-review-complete`, add `bot-fix-failed`
   b. Add Jira comment:
      ```
      ## PR Closed Without Merge
      **PR**: [#N](<pr_url>) was closed without merging.

      The fix was rejected or abandoned. To retry with a new approach,
      add the `bot-retry` label. To opt out, add `no-autofix`.
      ```

## Phase 5: Human Cancellation

Check for tickets where a human has requested cancellation by adding the
`bot-cancelled` label. This phase runs BEFORE stale cleanup so that
explicit human intent takes priority over automated stale detection.

1. Query:
   ```
   JQL: labels = autofix AND labels = bot-cancelled AND labels NOT IN (bot-fix-failed, bot-merged) AND project IN (<WATCHED_PROJECTS>)
   ```

2. For each ticket:
   a. Check for active Ambient sessions with label `jira-ticket=<TICKET-KEY>`
      in non-terminal phases.
   b. For each active session: attempt to stop it via the Ambient session
      MCP. If session stop is not available or fails, log a warning — the
      session will run until its TTL expires, but no further label-driven
      transitions will occur.
   c. Remove `bot-cancelled` and any other `bot-*` labels present
      (`bot-in-progress`, `bot-ready-for-review`, `bot-review-fix`,
      `bot-review-complete`, `bot-retry`). Add `bot-fix-failed`.
      Removing `bot-retry` prevents a simultaneous cancel+retry from
      triggering an immediate retry in Phase 8 of the same cycle.
   d. Add Jira comment (conditional on `no-autofix` presence):

      If `no-autofix` is also present on the ticket:
      ```
      ## Pipeline Cancelled
      Cancelled by human intervention. Ticket is opted out of automation
      (`no-autofix` label present).
      ```

      If `no-autofix` is NOT present:
      ```
      ## Pipeline Cancelled
      Cancelled by human intervention (`bot-cancelled` label detected).
      Active sessions have been stopped (or will expire at TTL).

      To retry, add the `bot-retry` label.
      To opt out permanently, add `no-autofix`.
      ```

## Phase 6: Stale Session Cleanup

1. Query Ambient for sessions with label `type=issue-fix` OR `type=review-fix`
   OR `type=issue-review` in terminal phases (Completed, Failed, Stopped).

2. For each terminal session:
   a. Extract `jira-ticket` label to get the ticket key
   b. Check if the Jira ticket still has `bot-in-progress`, `bot-review-fix`,
      or `bot-ready-for-review` (for stale review sessions)
   c. If yes — the session ended without updating Jira:
      - For `bot-in-progress` or `bot-review-fix`: atomic label swap to
        `bot-fix-failed` (follow Label Swap Protocol)
      - For `bot-ready-for-review` (stale review): leave label in place
        so the watcher re-dispatches a new review session on next cycle
      - Add comment: "Agent session ended without completing. Session: <link>. Status: <phase>. To retry, add the `bot-retry` label."

## Phase 7: Missing Info Re-Check

Re-validate tickets stuck in `bot-missing-info` to see if the user added
the required information. This eliminates the need for users to manually
remove the label.

1. Query:
   ```
   JQL: labels = autofix AND labels = bot-missing-info AND project IN (<WATCHED_PROJECTS>)
   ```

2. For each ticket (max 5 per cycle to avoid TTL exhaustion):
   a. Re-parse the ticket **description only** for a `**Repository**:` URL.
      Then check comments — but **skip comments whose body starts with any
      known bot comment header** (prefix match — the header may be
      followed by additional text, e.g., `## Fix Plan (v1 — APPROVED)`):
      `## Missing Information`, `## Fix Applied`, `## Fix Failed`,
      `## Review-Fix Failed`, `## Review-Fix Cycle`,
      `## Agent Session Started`, `## PR Merged`, `## Agent Code Review`,
      `## Fix Plan`, `## Plan Compliance Failed`, `## Audit`,
      `## Pipeline Cancelled`, `## PR Closed Without Merge`.
      These bot-generated comments may contain example or error-quoted
      URLs that should not be treated as valid input.
   b. If a valid repo URL is now present:
      - Validate it (same checks as Phase 1 step 2: HTTPS, allowed hosts,
        no credentials, no path traversal)
      - If valid: remove `bot-missing-info` label (follow Label Swap Protocol)
      - Add comment: "Repository URL detected. Ticket re-queued for
        processing."
      - The ticket will be picked up by Phase 1 on the NEXT watcher cycle
        (not this cycle — avoids double-processing).
   c. If still missing or invalid: skip (will re-check next cycle).
   d. **Staleness reminder**: if the ticket has had `bot-missing-info` for
      more than 7 days (check the timestamp of the `## Missing Information`
      comment), post a follow-up comment — but only if no `Reminder:`
      comment has been posted yet:
      ```
      Reminder: This ticket is still waiting for a valid Repository URL.
      Add it to the ticket description and the bot will detect it
      automatically.
      ```

## Phase 8: Retry Failed Tickets

Process tickets where a user has requested a retry by adding the
`bot-retry` label.

1. Query:
   ```
   JQL: labels = autofix AND labels = bot-fix-failed AND labels = bot-retry AND project IN (<WATCHED_PROJECTS>)
   ```

2. For each ticket:
   a. Count prior `## Fix Failed` comments. Subtract 1 for the initial
      attempt to get the retry count (e.g., 2 Fix Failed comments = 1
      prior retry).
   b. If retry count >= `MAX_FIX_RETRIES` (default 2 from config.env):
      - Remove `bot-retry` label
      - Add comment: "Maximum retries (2) reached. This ticket needs human
        intervention. Prior failures are documented in comments above."
      - Skip this ticket.
   c. Re-parse description and comments for Repository URL (same parsing
      as Phase 1, skipping known bot comment headers as defined in Phase 7).
   d. Validate the URL (same as Phase 1 step 2).
   e. If URL missing or invalid: remove `bot-retry`, add comment explaining
      the issue. Skip.
   f. Atomic label swap (follow Label Swap Protocol):
      remove `bot-fix-failed` and `bot-retry`, add `bot-in-progress`.
   g. Continue with normal dispatch (same as Phase 1 steps 4-10: check
      active session, check concurrency, create session).
      **If session creation fails:** rollback by removing `bot-in-progress`
      and re-adding both `bot-fix-failed` and `bot-retry` (preserving
      user intent so the next watcher cycle retries automatically).
      Post comment: "Retry session creation failed — will retry on
      next cycle."
      The session prompt should include:
      ```
      This is retry N. Check prior ## Fix Failed comments on the Jira
      ticket for context on what was previously attempted and why it failed.
      Avoid repeating the same approach.
      ```

## Cycle Summary

After all phases, post a summary to Slack (if `SLACK_WEBHOOK_URL` is configured):

```
Issue Fix Agent — Watcher Cycle Summary
- New tickets processed: N
- Missing info (awaiting user): N
- Missing info auto-recovered: N
- Fix sessions dispatched: N
- Review sessions dispatched: N
- Review-fix sessions dispatched: N
- Retries dispatched: N
- Merged PRs updated: N
- Closed PRs detected: N
- Cancelled by human: N
- Stale sessions cleaned: N
- Errors: N

Completed Sessions (this cycle):
  <ticket-key>: <model>, <duration>m (<outcome>, fix confidence: <HIGH/MEDIUM/LOW>)
  ...
  Total Opus-minutes: Nm | Sonnet-minutes: Nm

LOW confidence fixes awaiting review: N
```

Duration and Fix Confidence are extracted from `## Fix Applied` Jira
comments on sessions that completed since the last cycle. Sessions
still in progress are not included.

Then exit the session.
