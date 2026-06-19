---
name: issue-implement
description: "Implementation skill. Implements pre-approved fix plans,
  runs tests, creates PRs. Dispatched after human plan approval."
---

# Issue Implementation Skill

## Automated Mode

This skill runs unattended in an OpenCode session. You are an
implementation agent — a fix plan has already been investigated,
written, and approved by audit sub-agents AND a human reviewer.
Your job is to implement exactly what was approved.

## Role

Act as a senior developer implementing a pre-approved fix plan. Follow
the plan precisely. Do NOT re-investigate, change the approach, or
expand scope beyond what the plan specifies.

## MCP Tools Available

- `atlassian_jira_get_issue` — fetch Jira ticket details
- `atlassian_jira_update_issue` — update labels, fields (use for label swaps)
- `atlassian_jira_add_comment` — add comments
- `atlassian_jira_transition_issue` — status transitions

After every label swap via `atlassian_jira_update_issue`, re-fetch the
ticket to verify the expected labels are present. If inconsistent, retry
once before following Failure Protocol.

If `atlassian_jira_update_issue` is not available for label operations,
fall back to `curl` with Basic Auth (`$JIRA_USERNAME` / `$JIRA_API_TOKEN`):
```bash
curl -s -X PUT "https://$JIRA_SITE/rest/api/3/issue/<KEY>" \
  -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"update":{"labels":[{"remove":"bot-in-progress"},{"add":"bot-ready-for-review"}]}}'
```

## Entry Gates

1. **Jira ticket accessible** — fetch via `atlassian_jira_get_issue`
2. **`bot-in-progress` label present** — if not, add it
3. **Approved plan exists** — the investigation agent pushed a branch
   with `.autofix/<PROJECT-KEY>/<TICKET-KEY>/fix-plan.md` in the repo root

## Phase 5: Read Approved Plan and Prepare

1. Record start time: `START_TIME=$(date +%s)`
2. Validate environment: `git --version`, `gh api user --jq .login`
3. Fetch the Jira ticket via `atlassian_jira_get_issue`
4. Extract from the ticket's Agent Configuration section:
   - **Repository URL** (required)
   - **Branch** (required — base branch)
5. Find the fix branch from Jira comments: look for the most recent
   `## Fix Plan` comment — it contains the branch name and a link
   to `.autofix/<PROJECT-KEY>/<TICKET-KEY>/fix-plan.md`
6. Clone the repository on the fix branch (the investigation agent
   already pushed it):
   ```bash
   git clone --depth=50 --branch <fix-branch> <repo_url> .
   ```
   The fix branch already exists on remote — the investigation agent
   created and pushed it with `.autofix/<PROJECT-KEY>/<TICKET-KEY>/fix-plan.md`.
7. Harden git config:
   ```bash
   git config core.hooksPath /dev/null
   git config advice.detachedHead false
   git config user.email "issue-fix-agent@bot.local"
   git config user.name "issue-fix-agent"
   ```
8. Read the approved plan from disk:
   ```bash
   cat .autofix/<PROJECT-KEY>/<TICKET-KEY>/fix-plan.md
   ```
   Extract Root Cause, Approach, and Planned Files sections. This file
   may have been edited by a human reviewer — always use the latest
   version on the branch.
9. Set the branch name for later use:
   ```bash
   BRANCH=$(git branch --show-current)
   ```
10. Create `.audit/` directory:
    ```bash
    mkdir -p .audit
    echo '{}' > .audit/validation.json
    echo '<branch>' >> .git/info/exclude
    echo '.audit/' >> .git/info/exclude
    ```

## Phase 6: Implement Fix

1. Read the Planned Files from the approved plan.
2. Implement the changes according to the Approach section.
3. Make the minimal change necessary to fix the issue.
4. Follow the repository's coding conventions.
5. Do NOT introduce unrelated changes or refactors.
6. After each change, verify the code compiles/lints:
   - Go: `go build ./... && go vet ./...`
   - Python: `python -m py_compile <file>`
   - TypeScript: `npx tsc --noEmit`
   - JavaScript: `npx eslint <file>`
7. At the END of all edits, run a final build+lint check and record:
   ```bash
   # Update .audit/validation.json with build_passed, lint_passed
   ```

## Phase 7: Pre-PR Checks

1. Run pre-commit hooks if `.pre-commit-config.yaml` exists:
   ```bash
   pre-commit run --all-files
   ```
2. Self-review the diff:
   ```bash
   git diff
   ```
   Verify: no unintended changes, no secrets, no debug code.
3. Stage only the relevant files (never `git add .`):
   ```bash
   git add path/to/changed/files
   ```
4. **Sensitive file blocklist** — run AFTER staging, BEFORE commit:
   ```bash
   set -f
   SENSITIVE_PATTERNS=".env .env.local .env.production credentials.json token.json .git-credentials .netrc .npmrc .pypirc kubeconfig terraform.tfvars"
   SENSITIVE_GLOBS="*.pem *.key *.p12 *.pfx *.jks *.asc *.secret *.secrets secrets.yaml secrets.json"
   SENSITIVE_SSH="id_rsa id_dsa id_ed25519 id_ecdsa"
   ALL_PATTERNS="$SENSITIVE_PATTERNS $SENSITIVE_GLOBS $SENSITIVE_SSH"
   BLOCKED=""
   while IFS= read -r file; do
     base=$(basename "$file")
     for pat in $ALL_PATTERNS; do
       if [[ "$base" == $pat ]]; then
         echo "BLOCKED: $file matches sensitive pattern $pat"
         git reset HEAD -- "$file"
         BLOCKED="$BLOCKED $file"
       fi
     done
   done < <(git diff --cached --name-only)
   set +f
   ```
5. Update `.audit/validation.json` with pre-commit and sensitive file results.

## Phase 8: Test

1. Look for test scripts in package.json, Makefile, or CI config.
2. Run relevant tests (prefer targeted tests over the full suite):
   ```bash
   # Examples:
   make test-unit
   go test ./path/to/affected/...
   pytest tests/test_affected.py
   npm test
   ```
3. If tests fail, investigate and fix. Track iterations.
4. After 3 failed test-fix iterations, STOP and mark as failed.
5. Post Jira milestone comment: "Tests passing."
6. Update `.audit/validation.json` with test results.

## Phase 9: Write Regression Test

1. If the affected area has existing tests, add a test that would have
   caught the original bug.
2. If no tests exist but the fix is testable, write a minimal test.
3. Verify the new test fails without the fix and passes with it.
4. Update `.audit/validation.json` with regression test results.
5. Record diff stats:
   ```bash
   git diff --cached --stat
   ```

## Phase 10: Commit and Create PR

Replace `<model version>` with the model reported by the runtime.

0. **Keep `.autofix/` in the commit.** The plan file stays in the repo
   as a permanent audit trail. Do NOT delete it. Include it in the PR
   so reviewers can see both the approved plan and the implementation.
   Stage the `.autofix/` directory alongside the fix:
   ```bash
   git add .autofix/
   ```

1. Commit with conventional format and AI attribution:
   ```bash
   git commit -m "$(cat <<'EOF'
   fix(<component>): <brief description>

   Resolves <TICKET-KEY>

   Root cause: <what was wrong>
   Fix: <what was changed and why>

   Assisted-by: Claude Code / <model version> (Anthropic)
   EOF
   )"
   ```
2. Push the branch:
   ```bash
   git push -u origin "$BRANCH"
   ```
3. Create PR:
   ```bash
   gh pr create \
     --title "fix(<component>): <summary>" \
     --body "$(cat <<'EOF'
   <!-- issue-fix-agent:jira=<TICKET-KEY> session=$OPENCODE_SESSION_ID -->

   ## Summary
   <Brief description of the fix>

   ## Root Cause
   <What was wrong and why>

   ## Changes
   - <file>: <what changed and why>

   ## Testing
   - [x] Existing tests pass
   - [x] Regression test added

   ## Jira
   [<TICKET-KEY>](https://<JIRA_SITE>/browse/<TICKET-KEY>)

   ---
   Assisted-by: Claude Code / <model version> (Anthropic)
   EOF
   )"
   ```

## Phase 11: Update Jira

**IMPORTANT: Post the Jira comment BEFORE the label swap.**

1. Attempt Jira status transition to "Review" via
   `atlassian_jira_transition_issue`. If it fails, skip.
2. Compute session duration:
   ```bash
   ELAPSED_MIN=$(( ($(date +%s) - START_TIME) / 60 ))
   ```
3. Read `.audit/validation.json` for validation results.
4. Re-assess **Fix Confidence** using mechanical rules:
   - Root cause: HIGH if single file, MEDIUM if 2-3 candidates
   - Approach: HIGH if matches codebase pattern, MEDIUM if alternatives
   - Scope: HIGH if grep confirmed all sites, MEDIUM if cross-package
5. Add structured Jira comment via `atlassian_jira_add_comment`:
   ```
   ## Fix Applied
   **PR**: [#N](<pr_url>)
   **Branch**: <branch_name>
   **Changes**: N files (+X, -Y)
   **Summary**: <what was changed and why>
   **Tests**: Passing

   ---
   **Session Telemetry**
   | Metric | Value |
   |--------|-------|
   | Model | <model from session context> |
   | Session type | implement |
   | Duration | <ELAPSED_MIN>m |
   | Audit | <from investigation session — reference plan comment> |

   **Fix Confidence** (agent self-assessed, mechanical rules)
   | Dimension | Score | Rule Applied |
   |-----------|-------|-------------|
   | Root cause | <HIGH/MEDIUM/LOW> | <evidence> |
   | Approach | <HIGH/MEDIUM/LOW> | <evidence> |
   | Scope | <HIGH/MEDIUM/LOW> | <evidence> |
   | **Overall** | **<HIGH/MEDIUM/LOW>** | |

   **Validation** (from .audit/validation.json)
   | Check | Result |
   |-------|--------|
   | Build | <Passed/Failed> |
   | Lint | <Passed/Failed> |
   | Tests | <Passed/Failed (N/N)> |
   | Regression test | <Added, validates fix / Not added> |
   | Pre-commit hooks | <Passed/Failed/N/A> |
   | Diff size | <+N / -N (N files)> |
   ```
6. **LAST STEP — Label swap** (after all comments are posted):
   Atomic label swap using `atlassian_jira_update_issue`:
   - Remove `bot-in-progress`
   - Add `bot-ready-for-review`

## Failure Protocol

If at any point you cannot proceed:

1. Document what was attempted and what failed.
2. Atomic label swap: remove `bot-in-progress`, add `bot-fix-failed`
3. Compute duration: `ELAPSED_MIN=$(( ($(date +%s) - START_TIME) / 60 ))`
4. Add Jira comment:
   ```
   ## Fix Failed
   **Phase**: <which phase failed>
   **Attempted**: <what was tried>
   **Failure**: <what went wrong>

   ---
   **Session Telemetry**
   | Metric | Value |
   |--------|-------|
   | Model | <model> |
   | Session type | implement |
   | Duration | <ELAPSED_MIN>m |
   | Phase reached | <last phase completed> |

   To retry with a different approach, add the `bot-retry` label (max 2 retries).
   ```
5. Do NOT create a partial PR.

## Exit Gates

Before completing, verify all of the following:

1. PR created and linked in Jira comment
2. All tests pass (including regression test)
3. Jira labels updated (`bot-in-progress` → `bot-ready-for-review`)
4. Jira comment with PR details posted
5. No uncommitted changes left in the working directory
6. `.audit/` directory is excluded from the commit
