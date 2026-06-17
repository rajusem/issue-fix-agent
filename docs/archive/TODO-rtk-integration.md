# TODO: RTK Integration — Pluggable Token Optimization

Integrate RTK (https://github.com/rtk-ai/rtk) as an optional,
flag-controlled token optimization layer for issue-fix-agent sessions.
RTK intercepts shell command outputs and filters noise (whitespace,
comments, boilerplate, duplication) before they reach the LLM context
window, achieving 60-90% token reduction.

## Problem

The audit loop (Phase 4B) creates significant context window pressure:
- 3-iteration worst case: 150-180K tokens against 200K limit
- Sub-agents receive file reads, grep results, git diffs as input
- Investigation phase (Phase 3) reads multiple source files
- Review agent processes full PR diffs

Without optimization, complex fixes risk hitting context limits,
degrading reasoning quality or requiring aggressive compaction.

## Why RTK

| Concern | How RTK Helps |
|---------|---------------|
| **Context window pressure** | 60-90% fewer tokens from shell commands = more room for reasoning |
| **Audit loop feasibility** | 3-iteration scenario drops from ~180K to ~100K tokens |
| **Session cost** | Fewer tokens = faster sessions = lower Opus/Sonnet spend |
| **Transparency** | Output is a valid subset of original — no RTK-specific markers, no behavior change |
| **Safety** | Falls back to raw output on filter failure, <10ms overhead |

### Token Savings Estimate (Per Fix Session)

| Operation | Frequency | Without RTK | With RTK | Savings |
|-----------|-----------|-------------|----------|---------|
| File reads (`cat`/`read`) | 20-30x | 40-60K | 8-12K | ~80% |
| `grep`/`find` | 8-15x | 16-30K | 3-6K | ~80% |
| `git status`/`diff`/`log` | 10-15x | 13-20K | 3-5K | ~76% |
| `cargo test`/`pytest`/`go test` | 3-5x | 15-25K | 1.5-2.5K | ~90% |
| `gh pr diff`/`gh pr view` | 2-3x | 6-10K | 1.5-2.5K | ~75% |
| **Total** | | **~90-145K** | **~17-28K** | **~80%** |

## Design: Pluggable via Flag

RTK integration is **optional and flag-controlled**. The system works
identically with or without RTK — it only affects token efficiency.

### Configuration (PE-004 resolution — 1 variable only)

Add to `config/config.env`:

```bash
# RTK Token Optimization (optional, opt-in)
RTK_ENABLED=false                # Master switch (default: false)
```

RTK version is pinned in the container image Dockerfile, not in
runtime config. `--verbose`/`--nocapture` flags are always respected
by RTK (hardcoded behavior, not configurable).

### Architecture

```
Session Start
  |
  v
Check $RTK_ENABLED
  |
  +-- false --> normal execution (no RTK, no overhead)
  |
  +-- true --> check if rtk binary exists (pre-installed in image)
                |
                v
              rtk init (installs Claude Code PreToolUse hook)
                |
                v
              Healthcheck: echo RTK_OK (verify hook works)
                |
                +-- fail --> remove hook, log warning, continue without RTK
                |
                +-- pass --> RTK active
                |
                v
              Shell commands intercepted by RTK:
                Agent runs: git status
                --> Hook rewrites to: rtk rewrite "git status"
                --> RTK filters output (strips noise)
                --> Returns filtered output to agent (~80% fewer tokens)

              EXCEPTION: During Phase 4B audit loop, RTK hook is
              temporarily uninstalled to prevent filtering of
              evidence validation commands. Re-installed after audit.
```

### Hook Mechanism

RTK integrates with Claude Code via a **PreToolUse hook** that
intercepts Bash tool calls. The hook:

1. Matches shell commands against RTK's registry (100+ commands)
2. If matched: rewrites the command through `rtk rewrite "<cmd>"`
3. If not matched: passes through unchanged
4. If RTK filter fails: falls back to raw output (never blocks)

The hook is installed in `.claude/settings.json` (session-level) by
`rtk init`. It does NOT modify the global Claude Code config or
`.claude/settings.local.json`.

**Settings collision prevention (RTK-004 resolution):** After
`rtk init`, verify that existing permissions in
`.claude/settings.local.json` are intact. If `rtk init` clobbered
any existing hooks, restore from backup and disable RTK for this
session.

### Session Lifecycle (RTK-002 + PE-005 resolution)

```
Phase 1 (Understand):
  1. Record START_TIME (FIRST — before any RTK work)
  2. Read Jira ticket (existing step)
  3. Agent checks $RTK_ENABLED (default: false)
  4. If true:
     a. Check if rtk binary exists: which rtk
     b. If not found: log "RTK binary not in image, skipping"
        (do NOT curl install at runtime — supply chain risk)
     c. Backup existing settings: cp .claude/settings.json .claude/settings.json.pre-rtk
     d. Run: rtk init
     e. Healthcheck: run 'echo RTK_HEALTHCHECK' through the hook
        - If output contains "RTK_HEALTHCHECK" → hook works
        - If hook crashes/hangs/corrupts → restore backup, log warning,
          continue without RTK (breaks circular dependency)
     f. Post Jira milestone: "RTK token optimization enabled (vX.Y.Z)"
  5. Continue with normal Phase 1

Phase 4B (Audit Loop) — RTK PAUSED:
  Before audit loop: rtk hooks uninstall
  (prevents RTK from filtering evidence validation commands like
  'test -f <file> && sed -n <line>p <file>' which need raw output)
  After audit loop: rtk init (re-enable if was enabled)

Phase 5-10 (Implementation):
  All shell commands automatically filtered by RTK hook
  Agent is unaware of RTK — output looks normal but shorter

Phase 10 (Update Jira) — RTK METRICS:
  Run: rtk gain --json
  Embed savings in Jira comment (data persists in Jira since
  SQLite is ephemeral in container)

Session End:
  Container destroyed — SQLite tracking data lost
  (all valuable data already posted to Jira in Phase 10)
```

### What RTK Filters (Relevant to issue-fix-agent)

| Command | What Gets Stripped | What's Preserved |
|---------|-------------------|------------------|
| `git status` | Empty sections, verbose hints | Changed files, branch info |
| `git diff` | Unchanged context lines, index headers | Added/removed lines, file paths |
| `git log` | Merge commits, GPG signatures | Commit hash, message, author, date |
| `grep -rn` | Duplicate matches, binary file warnings | Unique matches with file:line |
| `find` | Permission denied errors, hidden files | Matched paths |
| `cat`/`read` | Blank lines, comment blocks, license headers | Code content |
| `go test` | Passed test names, cache lines | Failed tests, error messages |
| `pytest` | Passed tests, fixture setup output | Failed tests, assertions |
| `cargo test` | Passed tests, doc-test boilerplate | Failed tests, panics |
| `gh pr diff` | Unchanged context, index lines | Changes, file paths |
| `gh pr view` | Boilerplate metadata | Title, body, status, files |

### What RTK Does NOT Filter

- MCP tool calls (Jira operations) — not shell commands
- Agent tool sub-agent prompts — text, not command output
- File writes/edits — not intercepted
- Commands with `--verbose`/`--nocapture` flags — respected when
  `RTK_RESPECT_VERBOSE=true`

## Impact on Existing Workflows

### issue-fix (most benefit)

| Phase | Commands Affected | Expected Savings |
|-------|-------------------|-----------------|
| Phase 1 (Understand) | None (Jira MCP) | 0% |
| Phase 2 (Prepare) | `git clone`, `git checkout` | Minimal |
| Phase 3 (Investigate) | `grep`, `find`, `cat`, `git log`, `git diff` | **60-80%** |
| Phase 4 (RCA) | File reads, `grep` | **70-80%** |
| Phase 4A (Write Plan) | File reads for plan | **70%** |
| Phase 4B (Audit Loop) | Sub-agent file reads, grep | **60-80%** |
| Phase 5 (Implement) | `go build`, `tsc`, linters | **50-70%** |
| Phase 6 (Pre-PR) | `git diff`, pre-commit | **70%** |
| Phase 7 (Test) | `go test`, `pytest`, `npm test` | **80-90%** |
| Phase 8 (Regression) | Test output | **80-90%** |
| Phase 9 (Commit/PR) | `git`, `gh pr create` | Minimal |
| Phase 10 (Update Jira) | None (Jira MCP) | 0% |

### issue-review

| Phase | Commands Affected | Expected Savings |
|-------|-------------------|-----------------|
| Phase 2 (Fetch PR) | `gh pr view`, `gh pr diff` | **60-75%** |
| Phase 3 (3-lens review) | File reads via `gh api` | **50-70%** |

### review-fix

| Phase | Commands Affected | Expected Savings |
|-------|-------------------|-----------------|
| Phase 3 (Clone) | `gh pr checkout` | Minimal |
| Phase 4 (Address) | File reads, `grep` | **60-80%** |
| Phase 5 (Test) | Test runners | **80-90%** |

### jira-watcher

No benefit — watcher uses MCP tools and `gh pr view --json` (structured
output, not verbose text).

## Installation (PE-002 resolution — supply chain security)

**Production: RTK is baked into the container image.** No runtime
installation from external URLs. The binary is pinned to a specific
version with SHA256 verification at image build time.

**Runtime `curl | sh` is NOT used.** This eliminates supply chain
risk (DNS hijack, CDN compromise, domain expiry).

### Container Image Integration

Add to the Ambient runner Dockerfile:

```dockerfile
# Install RTK for token optimization (pinned version + checksum)
ARG RTK_VERSION=0.40.0
ARG RTK_SHA256=<sha256-of-release-tarball>
RUN curl -fsSL "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk-x86_64-unknown-linux-gnu.tar.gz" \
      -o /tmp/rtk.tar.gz \
    && echo "${RTK_SHA256}  /tmp/rtk.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/rtk.tar.gz -C /usr/local/bin/ rtk \
    && rm /tmp/rtk.tar.gz \
    && rtk --version
```

This makes RTK available in all sessions. `rtk init` still runs
per-session (installs the Claude Code hook for that session only).

### Local Development / Testing

For local development (not production), developers can install via:

```bash
# Cargo (auditable registry)
cargo install rtk@0.40.0

# Homebrew (macOS)
brew install rtk
```

**Never use `curl | sh` in production pipelines.**

## Telemetry Integration (PE-003 resolution — ephemeral SQLite)

RTK tracks savings in a local SQLite database that is **ephemeral** —
destroyed when the container exits. To preserve the data, the agent
calls `rtk gain --json` in Phase 10 and embeds results in the Jira
comment (durable artifact).

### Capture in Phase 10

```bash
rtk gain --json
```

Output:
```json
{
  "total_commands": 87,
  "total_input_tokens": 145000,
  "total_output_tokens": 29000,
  "savings_pct": 80.0,
  "top_commands": [
    {"cmd": "git diff", "calls": 15, "savings_pct": 76},
    {"cmd": "grep", "calls": 12, "savings_pct": 82},
    {"cmd": "pytest", "calls": 4, "savings_pct": 91}
  ]
}
```

### Embed in Jira Comment

Add to the `## Fix Applied` comment in Phase 10:

```
**RTK Token Savings** (if RTK was enabled)
| Metric | Value |
|--------|-------|
| Commands filtered | 87 |
| Tokens saved | 116K (80%) |
| Est. cost saved | ~$1.80 |
```

### Canary Check (PE-006 resolution — output corruption detection)

If `rtk gain` reports >95% savings on any single command, log a
warning in the Jira comment: "RTK savings unusually high on <cmd>
(>95%) — verify output was not over-filtered." This flags potential
corruption for human review.

## Watcher Integration (RTK-003 resolution)

The watcher reads `RTK_ENABLED` from config.env and passes it in the
session prompt — same pattern as other config values. **The watcher
skill file needs to be updated** to include RTK_ENABLED in the prompt
template.

```json
{
  "prompt": "... RTK_ENABLED=<value from config> ...",
  "name": "fix-<ticket-key>",
  ...
}
```

The fix agent reads `$RTK_ENABLED` in Phase 1 and conditionally
runs `rtk init`.

## Rollback / Disable

Setting `RTK_ENABLED=false` in config.env (or not setting it at all)
completely disables RTK. No hooks are installed, no commands are
intercepted. The system behaves exactly as it does today.

If RTK causes issues mid-session, the agent can disable it:

```bash
rtk hooks uninstall
```

This removes the PreToolUse hook and all subsequent commands run
unfiltered.

## Files to Change

| File | Change | Effort |
|------|--------|--------|
| `config/config.env` | Add `RTK_ENABLED=false` (1 variable only) | 2 min |
| `workflows/issue-fix/skills/issue-fix.md` | Add RTK install step to Phase 1 (conditional, with healthcheck + backup/restore); add RTK pause/resume around Phase 4B audit loop; add rtk gain to Phase 10 | 15 min |
| `workflows/issue-fix/CLAUDE.md` | Document RTK availability, flag, and audit loop pause behavior | 5 min |
| `workflows/jira-watcher/skills/jira-watcher.md` | Pass RTK_ENABLED in session prompt template | 5 min |
| `docs/Architecture.md` | Add RTK as optional optimization layer in system context diagram | 10 min |
| `docs/setup-and-testing.md` | Add RTK test scenario (Test 15: verify savings with RTK enabled) | 10 min |

Platform-level (not per-workflow, separate from this implementation):

| File | Change | Effort |
|------|--------|--------|
| Container image (Dockerfile) | Pre-install pinned RTK binary with SHA256 verification | 10 min |

## Open Questions

**Resolved by audit Round 1:**
- ~~Install method?~~ → Baked in container image, pinned + SHA256 verified
- ~~RTK savings in Jira or just logs?~~ → Embedded in Phase 10 Jira comment
- ~~Minimum RTK version?~~ → Pinned in Dockerfile, not runtime config
- ~~Config variables count?~~ → 1 variable only (RTK_ENABLED)
- ~~Hook conflict with audit sub-agents?~~ → RTK paused during Phase 4B

**Still open (defer to v2):**
- [ ] Should RTK be enabled by default once validated, or always opt-in?
- [ ] Should review and review-fix workflows also run rtk init?
      (v1 is fix-agent-only)
- [ ] Should RTK support per-project or per-ticket opt-in for gradual
      rollout?
- [ ] RTK license and telemetry compliance review (does RTK phone home?)

## Acceptance Criteria

- [ ] `RTK_ENABLED=false` (default): no RTK initialized, no hooks, no
      behavior change — system works exactly as today
- [ ] `RTK_ENABLED=true` + RTK binary in image: hook installed in
      Phase 1, commands filtered transparently
- [ ] `RTK_ENABLED=true` + RTK binary NOT in image: log warning
      "RTK binary not found, skipping", continue without RTK
- [ ] `--verbose` and `--nocapture` flags on commands are respected
- [ ] Healthcheck after `rtk init`: if hook fails, restore backup
      settings, log warning, continue without RTK
- [ ] Phase 4B audit loop: RTK hook paused (uninstalled before loop,
      re-installed after) to prevent filtering evidence validation
- [ ] Phase 10: `rtk gain --json` output embedded in Jira comment
- [ ] Canary: if any command shows >95% savings, warning logged
- [ ] If RTK filter fails on a specific command: raw output returned
      (RTK's built-in fallback)
- [ ] No `curl | sh` in production sessions — RTK binary comes from
      the container image only
- [ ] `.claude/settings.json` backup created before `rtk init`,
      restored on failure
