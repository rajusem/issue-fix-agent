# TODO: Cost, Telemetry & Model Confidence Tracking

Track token usage, API spend, session duration, model identity, and
agent confidence scores across all workflows to enable cost attribution
per ticket, budget alerts, quality gating, and efficiency optimization.

## Current State (Post Audit Loop + RTK Implementation)

Some telemetry capabilities already exist from prior work:

| Capability | Status | Where |
|------------|--------|-------|
| RTK token savings (if enabled) | **DONE** | Phase 10 Jira comment (`rtk gain --json`) |
| Audit loop confidence (plan-level) | **DONE** | Fix plan schema has per-dimension confidence with proof |
| Audit iteration scoring | **DONE** | Iteration records track per-auditor verdicts, findings, convergence |
| Review per-finding confidence | **DONE** | Each review finding has HIGH/MEDIUM/LOW confidence |
| Wall-clock TTL tracking | **DONE** | START_TIME recorded in Phase 1, used for TTL checkpoints |
| Diff stats in Jira comment | **DONE** | `## Fix Applied` has `Changes: N files (+X, -Y)` |
| Session link in Jira | **DONE** | All comments include session link |

**What's NOT done (the scope of this TODO):**

| Capability | Status | Gap |
|------------|--------|-----|
| Confidence in `## Fix Applied` comment | **NOT DONE** | Fix agent doesn't report per-dimension confidence on the fix itself |
| Confidence in `## Agent Code Review` comment | **NOT DONE** | Review agent doesn't report per-lens confidence |
| Validation signals (build, lint, tests, secrets) | **NOT DONE** | Phases 5-8 run these checks but don't report structured pass/fail |
| Model identity (runtime ID, provider) | **NOT DONE** | No mechanism to capture actual model vs config |
| Session duration in Jira comment | **NOT DONE** | START_TIME exists but elapsed isn't reported |
| Watcher cost estimates in Slack | **NOT DONE** | Slack summary has counts only, no cost |
| Per-ticket aggregate cost | **NOT DONE** | No aggregation mechanism |

## Problem

Today the `## Fix Applied` Jira comment contains: PR URL, branch,
changes summary, tests status, and session link. It does NOT contain:

- How confident the agent is in its fix (reviewers can't prioritize)
- Whether build/lint/tests/secrets scans passed (only "Tests: Passing")
- Which model actually ran (Opus? Sonnet? Which version?)
- How long the session took
- How much it cost

A human reviewer looking at the Jira ticket has no way to distinguish
a high-confidence, fully-validated fix from a best-guess with partial
test coverage.

## Design: Telemetry Footer in Jira Comments

The primary delivery mechanism is a **structured telemetry footer**
appended to each workflow's final Jira comment. This is:
- **Durable** — Jira comments persist forever
- **Queryable** — humans can scan, and JQL can search comment text
- **Zero infrastructure** — no external telemetry backend needed
- **Incremental** — each section can be added independently

### Fix Agent: `## Fix Applied` Footer

Add after the existing comment fields:

```
## Fix Applied
**PR**: [#42](https://github.com/org/repo/pull/42)
**Branch**: PROJ-123/fix-null-check
**Changes**: 3 files (+12, -3)
**Summary**: Added null check in handleRequest()
**Tests**: Passing
**Session**: <session_link>

---
**Session Telemetry**
| Metric | Value |
|--------|-------|
| Model | claude-opus-4-6 (runtime: claude-opus-4-6-20260501) |
| Duration | 42m |
| Audit | 2 iterations, approved |

**Fix Confidence** (agent self-assessed, mechanical rules)
| Dimension | Score | Rule Applied |
|-----------|-------|-------------|
| Root cause | HIGH | Single file changed, clear symptom-to-cause trace |
| Approach | HIGH | Matches existing pattern in codebase, grep confirmed |
| Scope | MEDIUM | 3 files changed, 1 cross-package dependency |
| **Overall** | **HIGH** | |

Uses SAME dimensions as Plan Confidence (Phase 4A): root cause,
approach, scope. Re-assessed after implementation based on what
actually happened.

**Validation** (deterministic, from `.audit/validation.json`)
| Check | Result |
|-------|--------|
| Build | Passed |
| Lint | Passed |
| Tests | Passed (47/47) |
| Regression test | Added, validates fix |
| Pre-commit hooks | Passed |
| Diff size | +12 / -3 (3 files) |

**RTK Token Savings** (if enabled)
| Metric | Value |
|--------|-------|
| Commands filtered | 87 |
| Tokens saved | 116K (80%) |
```

### Review Agent: `## Agent Code Review` Footer

Add after the existing verdict:

```
## Agent Code Review — Ready for Human Review
**PR**: [#42](...)
**Files Reviewed**: 3 files (+12, -3)
**Lenses**: Correctness, Security, Quality
**Findings**: None blocking
**Verdict**: Ready for human final review and merge

---
**Review Confidence** (per-lens, agent self-assessed)
| Lens | Score | Notes |
|------|-------|-------|
| Correctness | HIGH | All code paths traced, no logic issues |
| Security | HIGH | No injection/credential risks in changes |
| Quality | MEDIUM | Style matches repo, minor naming suggestion (NIT) |
| **Overall** | **HIGH** | |

**Plan Compliance**: 3/3 planned files changed, 0 unplanned (PASS)

**Session Telemetry**
| Metric | Value |
|--------|-------|
| Model | claude-sonnet-4-6 |
| Duration | 8m |
```

### Review-Fix Agent: `## Review-Fix Cycle` Footer

Add after the existing cycle summary:

```
## Review-Fix Cycle 1/3
**Findings Addressed**: 2 of 2
**Changes**: 1 file (+4, -2)
**Details**:
- [MAJOR-001]: Fixed by adding error check
- [MAJOR-002]: Fixed by removing unused import

---
**Session Telemetry**
| Metric | Value |
|--------|-------|
| Model | claude-opus-4-6 |
| Duration | 12m |
```

### Watcher: Slack Summary with Cost Estimates

Extend the existing Slack notification:

```
Issue Fix Agent — Watcher Cycle Summary
- New tickets processed: 3
- Fix sessions dispatched: 2
- Review sessions dispatched: 1
- Merged PRs: 1
- Failed: 1
- Stale cleaned: 0

Duration (this cycle):
  fix-proj-123:   Opus, 42m (merged, fix confidence: HIGH)
  fix-proj-456:   Opus, 58m (failed - max audit iterations)
  review-proj-123: Sonnet, 8m (passed)
  Total Opus-minutes: 100m | Sonnet-minutes: 8m

LOW confidence fixes awaiting review: 0
```

Duration is tracked as model-minutes (Opus-minutes, Sonnet-minutes),
NOT converted to dollar amounts. Dollar estimates require token counts
which are not available without Ambient API or OTEL. Presenting
dollar amounts with cents precision from wall-clock time would be
misleading — duration correlates with cost but is not cost.

For rough budgeting, operators can use external rate cards to convert
model-minutes to estimated spend.

## How to Capture Each Data Point

### Model Identity

The agent can self-report the model from its session context. Claude
Code sessions know which model they are running.

```
Model: <model from session context>
```

If the runtime model ID differs from the configured model (e.g.,
config says `claude-opus-4-6` but runtime resolves to
`claude-opus-4-6-20260501`), note both. The agent should include
whatever model identifier is available in its context.

**v1 approach:** Report the configured model name (from the session
prompt). This is always available.

**v2 approach:** Parse runtime model ID from Claude CLI output or
OTEL metrics if Ambient exposes them.

### Session Duration

Already tracked — START_TIME is recorded in Phase 1. Compute elapsed
at Phase 10:

```bash
ELAPSED_SEC=$(( $(date +%s) - START_TIME ))
ELAPSED_MIN=$(( ELAPSED_SEC / 60 ))
```

### Confidence Scores (ARCH-001 + AGT-003 resolution)

**Naming convention:** Three distinct confidence labels across the
lifecycle:

| Stage | Label | Dimensions |
|-------|-------|------------|
| Phase 4A (plan) | **Plan Confidence** | Root cause, Approach, Scope |
| Phase 10 (fix) | **Fix Confidence** | Root cause, Approach, Scope (re-assessed) |
| Review Phase 5 | **Review Confidence** | Correctness, Security, Quality (per-lens) |

Plan and Fix Confidence use the SAME 3 dimensions so they can be
compared. If Plan Confidence was HIGH but Fix Confidence drops to
MEDIUM, it signals something unexpected happened during implementation.

**Mechanical scoring rules (AGT-002 resolution):**

Root cause:
- HIGH: single file/function, clear trace or reproduction
- MEDIUM: 2-3 candidates, narrowed to most likely
- LOW: multiple possible causes, fix addresses symptoms

Approach:
- HIGH: matches existing codebase pattern, single valid fix
- MEDIUM: reasonable but alternatives exist
- LOW: best guess, no precedent

Scope:
- HIGH: grep confirmed all call sites, no cross-package impact
- MEDIUM: multiple packages, some call sites may be missed
- LOW: broad impact, cannot verify all consumers

Review Confidence uses per-lens scoring (different dimensions).

### Validation Signals (PE-002 resolution — file-based persistence)

Phases 5-8 already run build, lint, tests, pre-commit, and regression
tests. The gap is that results are NOT persisted or reported. The
agent cannot reliably remember pass/fail states across a 150-minute
session with context compaction.

**Solution:** Write validation results to `.audit/validation.json`
at each phase (same pattern as `.audit/approved-plan.md`). Read back
at Phase 10 to compile the telemetry footer.

```bash
# Phase 5: at the END of implementation (after all edits, final build+lint)
# NOT after each per-file check — write once when Phase 5 completes
echo '{"build_passed": true, "lint_passed": true}' > .audit/validation.json

# Phase 6: update with pre-commit result
# (read existing, merge, write back)

# Phase 7: update with test results
# (add tests_passed, tests_total, tests_failed)

# Phase 8: update with regression test
# (add regression_added, regression_validates)

# Before Phase 9: add diff stats
# (add diff_additions, diff_deletions, files_touched)
```

At Phase 10, the agent reads `.audit/validation.json` and formats
the Validation table. This survives context compaction because the
data is on disk, not in conversation memory.

**AGT-001 resolution:** The telemetry footer template MUST be
embedded directly in Phase 10 of issue-fix.md as the output format.
The agent follows the template in front of it, not a reference to a
design doc 600 lines earlier. The template in Phase 10 should show
the exact Jira comment structure with all 4 sections (Session
Telemetry, Fix Confidence, Validation, RTK).

### Watcher Cost Estimates

The watcher queries terminal sessions in Phase 4 (Post-Merge) and
Phase 5 (Stale Cleanup). It can compute duration from session
metadata (start time, end time) and multiply by per-model cost rate.

The watcher already knows which model was used (it set it when
creating the session). Duration can come from session metadata if
Ambient exposes it, or from the `## Fix Applied` comment if the
fix agent reports duration there.

### Failure Telemetry (GAP-001 resolution)

Failed sessions are arguably MORE important to track for cost
optimization. The `## Fix Failed` comment in the Failure Protocol
should include partial telemetry:

```
## Fix Failed
**Phase**: Phase 5 (Implement Fix)
**Attempted**: Added null check in handler.go
**Failure**: Tests failed after 3 iterations
**Session**: <session_link>

---
**Session Telemetry**
| Metric | Value |
|--------|-------|
| Model | claude-opus-4-6 |
| Duration | 58m |
| Phase reached | Phase 7 (Test) |

**Partial Validation** (from `.audit/validation.json`)
| Check | Result |
|-------|--------|
| Build | Passed |
| Lint | Passed |
| Tests | Failed (3/47) |
```

This helps identify expensive failure patterns (e.g., tickets that
consistently fail at Phase 7 after 50+ minutes of Opus time).

## Implementation Plan

### Phase 1: Telemetry Footer in Fix Agent (Primary Value)

Add confidence + validation + duration to `## Fix Applied` comment
AND to `## Fix Failed` comment. Persist validation state to
`.audit/validation.json` across phases.

**Files to change:**
- `workflows/issue-fix/skills/issue-fix.md`:
  - Phase 4A: create `.audit/validation.json` (alongside approved-plan.md)
  - Phases 5-8: write pass/fail results to `.audit/validation.json`
  - Phase 10: read validation.json, compute duration, compile
    Fix Confidence + Validation + model into telemetry footer
  - Failure Protocol: read partial validation.json, include in
    `## Fix Failed` comment
- `CLAUDE.md` + `docs/Architecture.md`: update comment contract
  tables to include telemetry fields (ARCH-002); also add
  `## Fix Failed` as a recognized comment header (R2-002)

**Effort:** 45 min

### Phase 2: Telemetry in Review + Review-Fix

Add per-lens Review Confidence to review agent, session duration to
both review and review-fix. Both need START_TIME recording added to
their Phase 1 (AGT-004 resolution).

**Files to change:**
- `workflows/issue-review/skills/issue-review.md`:
  - Phase 1: add `START_TIME=$(date +%s)` recording
  - Phase 5: add Review Confidence footer + Session Telemetry (model, duration)
- `workflows/review-fix/skills/review-fix.md`:
  - Phase 1 (entry): add `START_TIME=$(date +%s)` recording
  - Phase 7: add Session Telemetry footer (model, duration)

**Effort:** 20 min

### Phase 3: Watcher Duration Summary

Add model-minutes and Fix Confidence to the Slack summary. Duration
and confidence are extracted from `## Fix Applied` Jira comments on
completed sessions.

**Files to change:**
- `workflows/jira-watcher/skills/jira-watcher.md` — Cycle Summary:
  add per-session model-minutes and Fix Confidence level

**Effort:** 15 min

### Phase 4: Centralized Dashboard (Future, Not in Scope)

Aggregate telemetry from Jira comments into a queryable format.
Options remain the same as the original design:
- Option A: Jira custom field for cost
- Option B: JSONL artifact from watcher
- Option C: OTEL collector (align with agentic-ci)

This requires infrastructure beyond skill file changes and is
deferred to a future initiative.

## Reference Implementations

| Project | What It Does | Relevant Pattern |
|---------|-------------|------------------|
| **agentic-ci** | OTEL collector: token counts, cost per model, API request counts | `agentic_ci/otel.py` |
| **harness** | Session Insights MCP: JSONL transcript analysis for token usage | `servers/session-insights/server.py` |
| **platform** | Langfuse + MLflow observability in the runner | `components/runners/ambient-runner/` |
| **autofix** | OTEL cost parsing, formatted in Jira comments | `src/jira_autofix/autofix_runner.py` |
| **autofix-skills** | Verdict schema: confidence + validation signals | `skills/autofix-triage/references/rubric-and-schema.md` |
| **cat-ai-helpers** | deep-verification: 5-phase confidence methodology | `agents/deep-verification.md` |

## Open Questions

**Resolved by prior work:**
- ~~Confidence in fix plan?~~ → Done in audit loop (Phase 4A/4B)
- ~~RTK token tracking?~~ → Done via `rtk gain` in Phase 10
- ~~Wall-clock timing?~~ → Done via START_TIME in Phase 1

**Resolved by this design:**
- ~~Should cost tracking be opt-in or always-on?~~ → Always-on.
  Confidence, validation, and duration are zero-cost metadata. No
  flag needed.
- ~~Should validation signals be hard gates or just recorded?~~ →
  Just recorded. Tests are already soft (3 retry iterations). The
  telemetry footer reports what happened, not what should happen.

**Still open (defer to v2):**
- [ ] Does Ambient expose token counts in session metadata?
- [ ] Can we access Claude CLI's OTEL output from within a session?
- [ ] What's the right cost model per token for Opus vs Sonnet on
      Vertex AI?
- [ ] Should we gate on confidence? (LOW confidence → bot-fix-failed)
- [ ] How to calibrate confidence? (track HIGH vs LOW merge rates)
- [ ] Should LOW confidence fixes be flagged in the Slack summary
      for human prioritization?

## Acceptance Criteria

### Phase 1: Fix Agent Telemetry (Primary)
- [ ] `## Fix Applied` includes `**Session Telemetry**` with model
      name (from session context) and duration (from START_TIME)
- [ ] `## Fix Applied` includes `**Fix Confidence**` with same 3
      dimensions as Plan Confidence (root cause, approach, scope),
      re-assessed after implementation using mechanical rules
- [ ] `## Fix Applied` includes `**Validation**` table populated
      from `.audit/validation.json` (build, lint, tests, regression,
      pre-commit, diff size)
- [ ] `.audit/validation.json` written at Phases 5-8, read at Phase 10
- [ ] `## Fix Failed` includes partial telemetry (model, duration,
      phase reached, partial validation from .audit/validation.json)
- [ ] Comment contract tables in CLAUDE.md and Architecture.md updated
      to reflect new telemetry fields in comment footers

### Phase 2: Review + Review-Fix Telemetry
- [ ] Review and review-fix skills record START_TIME in their Phase 1
- [ ] `## Agent Code Review` includes `**Review Confidence**` with
      per-lens scores (Correctness, Security, Quality)
- [ ] `## Agent Code Review` includes `**Session Telemetry**` with
      model and duration
- [ ] `## Review-Fix Cycle` includes `**Session Telemetry**` with
      model and duration

### Phase 3: Watcher Duration Summary
- [ ] Slack summary includes per-session model-minutes (not dollar
      amounts — duration is tracked, not cost)
- [ ] Slack summary includes Fix Confidence level for completed sessions
- [ ] LOW confidence fixes highlighted for human attention
- [ ] Duration data comes from completed sessions only (not in-progress)
