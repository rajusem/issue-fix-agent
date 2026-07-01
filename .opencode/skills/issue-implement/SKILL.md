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
  -d '{"update":{"labels":[{"remove":"bot-in-progress"},{"remove":"bot-plan-approved"},{"remove":"bot-plan-ready"},{"add":"bot-ready-for-review"}]}}'
```

## Entry Gates

1. **Jira ticket accessible** — fetch via `atlassian_jira_get_issue`
2. **Human approval verified** — check the ticket labels BEFORE adding
   any labels. The `bot-plan-approved` label must be present.
   If `bot-plan-approved` is NOT present:
   - Add Jira comment: "Implementation requires human approval. Please
     review the fix plan and add `bot-plan-approved` label to proceed."
   - Do NOT add `bot-in-progress`. Do NOT proceed — exit immediately.
3. **Approved plan exists** — the investigation agent either pushed a
   branch with `.autofix/<PROJECT-KEY>/<TICKET-KEY>/fix-plan.md` (when
   `PLAN_IN_PR=true`) or posted the full plan in a Jira comment (when
   `PLAN_IN_PR=false`)

## Phase 5: Read Approved Plan and Prepare

1. **Add `bot-in-progress` label** to signal the agent is actively working.
   Keep `bot-plan-approved` — it stays as proof of human approval until
   implementation completes. Both are removed at the end:
   - Success: remove `bot-in-progress` + `bot-plan-approved` + `bot-plan-ready`,
     add `bot-ready-for-review`
   - Failure: remove `bot-in-progress` + `bot-plan-approved` + `bot-plan-ready`,
     add `bot-fix-failed`
2. Post Jira milestone comment with session context:
   ```
   ## Agent Session Started
   Implementation agent has started working on this ticket.

   **Model**: <model from session context>
   **Environment**: <DEPLOY_MODE from prompt context>
   **FORK_MODE**: <FORK_MODE value>
   **PLAN_IN_PR**: <PLAN_IN_PR value>
   ```
3. Record start time: `START_TIME=$(date +%s)`
3. Validate environment: `git --version`, `gh api user --jq .login`
4. Fetch the Jira ticket via `atlassian_jira_get_issue`
4. Extract from the ticket's Agent Configuration section:
   - **Repository URL** (required)
   - **Branch** (required — base branch)
5. Find the fix branch from Jira comments: look for the most recent
   `## Fix Plan` comment — it contains the branch name.
6. Clone the repository on the fix branch. Check `${FORK_MODE:-false}`:

   First clean up any previous clone:
   ```bash
   rm -rf work 2>/dev/null
   ```

   **If `false` (default):** Clone directly from the ticket's repo URL:
   ```bash
   git clone --depth=50 --branch <fix-branch> <repo_url> work && cd work
   ```

   **If `true`:** The fix branch is on the FORK, not upstream. Compute
   the fork URL from the upstream URL:
   ```bash
   FORK_OWNER=$(gh api user --jq .login)
   REPO_NAME=$(basename "<repo_url>")   # e.g., "obs-mcp"
   git clone --depth=50 --branch <fix-branch> \
     "https://github.com/$FORK_OWNER/$REPO_NAME" work && cd work
   git remote add upstream <repo_url>   # upstream is read-only
   ```

7. Harden git config:
   ```bash
   git config core.hooksPath /dev/null
   git config advice.detachedHead false
   git config user.email "issue-fix-agent@bot.local"
   git config user.name "issue-fix-agent"
   ```
8. Read the approved plan. Check `${PLAN_IN_PR:-true}`:

   **If `true` (default):** Read from disk:
   ```bash
   cat .autofix/<PROJECT-KEY>/<TICKET-KEY>/fix-plan.md
   ```
   This file may have been edited by a human reviewer — always use
   the latest version on the branch.

   **If `false`:** Read from Jira. Use `atlassian_jira_get_issue` to
   fetch comments. Find the LAST (most recent) comment containing
   `## Fix Plan` and plan sections (Root Cause, Approach, Files to
   Change). If multiple `## Fix Plan` comments exist (from retries),
   always use the last one. Extract the plan content from that comment.

   In both cases, extract Root Cause, Approach, and Planned Files.
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
   Discover the test framework and relevant test files:
   a. **Detect framework** from project manifests:
      - Go: `go.mod` → `go test ./...`; check Makefile for `test` target
      - Python: `pyproject.toml`/`setup.cfg` → `pytest` or `python -m pytest`
      - Node: `package.json` → read `scripts.test`
      - Java: `pom.xml` → `mvn test`; `build.gradle` → `gradle test`
   b. **Map source→test files** by naming convention:
      - Go: `foo.go` → `foo_test.go` (same directory)
      - Python: `module.py` → `test_module.py` or `tests/test_module.py`
      - Node: `component.ts` → `component.test.ts` or `__tests__/component.ts`
      - Java: `Foo.java` → `FooTest.java` (test source tree)
   Prefer targeted tests over full suite. Fall back to full suite only if
   targeted tests cannot be identified.
2. Run relevant tests:
   ```bash
   # Examples:
   make test-unit
   go test ./path/to/affected/...
   pytest tests/test_affected.py
   npm test
   ```
3. If tests fail, investigate and fix. Track iterations.
3.5. **Pre-existing failure check** — this is a DIAGNOSTIC ONLY step.
   Before fixing a failing test, verify it's not a pre-existing failure:
   ```bash
   git stash
   if command -v timeout &>/dev/null; then
     timeout 300 bash -c '<same test command>' 2>&1 | tee /tmp/baseline-check.log
   else
     <same test command> 2>&1 | tee /tmp/baseline-check.log
   fi
   BASELINE_EXIT=$?
   git stash pop || (git checkout -- . && git stash drop)
   ```
   - Timeout: 5 minutes (300s). If exceeded, treat as inconclusive —
     log "Baseline check timed out" and assume the failure may be
     pre-existing. Proceed with caution.
   - If the test ALSO fails on the clean branch → pre-existing failure.
     Log to Jira: "Test `<name>` fails without agent changes (pre-existing)."
     Skip this test — do not count against pass/fail assessment.
   - If the test passes on clean branch → agent-introduced failure.
     Must fix before proceeding.
   - This is DIAGNOSTIC ONLY — do NOT change your fix approach based
     on baseline results. Record the result and proceed to the next step.
   - This check costs 3 tool calls but only triggers on failure.
   - If git stash pop fails (conflict from test-generated files),
     the fallback `git checkout -- . && git stash drop` restores
     the workspace cleanly.
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

0. **`.autofix/` handling** — check `${PLAN_IN_PR:-true}`:

   **If `true` (default):** Keep `.autofix/` in the commit as a permanent
   audit trail. Include it in the PR so reviewers can see the approved
   plan alongside the implementation. Stage it:
   ```bash

   **If `false`:** Do NOT stage `.autofix/`. The plan is in the Jira
   comment, not in the PR. Skip `git add .autofix/` and proceed to
   step 1.

   Stage the `.autofix/` directory (Mode 1 only):
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

   Assisted-by: OpenCode / <model version>
   EOF
   )"
   ```
2. Push the branch:
   ```bash
   git push -u origin "$BRANCH"
   ```
3. **Check for existing PR** before creating a new one (handles retries):
   ```bash
   EXISTING_PR=$(gh pr list --head "$BRANCH" --state open --json number --jq '.[0].number // empty')
   ```
   - If an open PR exists: update its title and body to match the current
     fix, then skip to Phase 11:
     ```bash
     gh pr edit "$EXISTING_PR" \
       --title "fix(<component>): <summary>" \
       --body "<PR body from template below>"
     ```
     Log to Jira: "Updated existing PR #$EXISTING_PR on branch $BRANCH."
   - If no open PR exists: create a new PR (proceed to step 4).
4. Create PR. Check `${FORK_MODE:-false}`:

   **If `false` (default):**
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
   Environment: <DEPLOY_MODE from prompt context>
   Assisted-by: OpenCode / <model version>
   EOF
   )"
   ```

   **If `true` (fork mode):** Create cross-repo PR from fork to upstream:
   ```bash
   FORK_OWNER=$(gh api user --jq .login)
   UPSTREAM_OWNER=$(basename "$(dirname "<repo_url>")")
   REPO_NAME=$(basename "<repo_url>")
   gh pr create \
     --repo "$UPSTREAM_OWNER/$REPO_NAME" \
     --head "$FORK_OWNER:$BRANCH" \
     --base <base-branch> \
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
   Environment: <DEPLOY_MODE from prompt context>
   Assisted-by: OpenCode / <model version>
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
   | Environment | <DEPLOY_MODE from prompt context> |
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
   - Remove `bot-in-progress`, `bot-plan-approved`, `bot-plan-ready`
   - Add `bot-ready-for-review`

## Failure Protocol

If at any point you cannot proceed:

1. Document what was attempted and what failed.
2. Atomic label swap: remove `bot-in-progress`, `bot-plan-approved`,
   `bot-plan-ready`, add `bot-fix-failed`
3. Compute duration: `ELAPSED_MIN=$(( ($(date +%s) - START_TIME) / 60 ))`
4. Add Jira comment:
   ```
   ## Fix Failed
   **Phase**: <which phase failed>
   **Failure Type**: <ENVIRONMENT|BUILD|TEST|PUSH|OTHER>
   **Attempted**: <what was tried>
   **Failure**: <what went wrong>

   Classify as the FIRST matching category (precedence order):
   - ENVIRONMENT: Token expired, tool missing, MCP unreachable, permissions
   - BUILD: Compilation error, missing import, type mismatch
   - TEST: Test assertion failures from agent changes
   - PUSH: Push rejected, branch conflict, PR creation failed
   - OTHER: Unexpected failure

   ---
   **Session Telemetry**
   | Metric | Value |
   |--------|-------|
   | Model | <model> |
   | Environment | <DEPLOY_MODE from prompt context> |
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
