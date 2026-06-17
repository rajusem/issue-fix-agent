# TODO: Smart Context & Signal-Driven Investigation

Enhance the fix agent's input parsing and investigation strategy to
accept richer context from Jira tickets (multiple skill URLs, knowledge
repos) and adapt investigation approach based on signals in the issue
description.

## Problem

Today the fix agent uses a one-size-fits-all investigation strategy:

1. Parse a single `**Skill**:` URL from the ticket (optional)
2. Grep for keywords, read files, trace code paths (Phase 3)
3. Hope to find the root cause through generic exploration

This misses two opportunities:

**Missed opportunity 1 — Domain knowledge:** Teams have shared
conventions, architecture docs, and coding patterns in separate repos
or multiple skill files. The agent can only ingest one skill URL,
so it misses team-specific context that would help it write better
fixes.

**Missed opportunity 2 — Investigation strategy:** A ticket that says
"this was working before the last deploy" is a regression — the agent
should immediately check git history (`git log`, `git bisect`,
`git blame`) rather than grep randomly. A ticket about "intermittent
failures" should look for race conditions. The current skill doesn't
adapt its investigation approach based on these signals.

## Current Ticket Format

```markdown
[Issue description]

---
## Agent Configuration
**Repository**: https://github.com/org/repo          (REQUIRED)
**Branch**: main                                      (optional)
**Commit**: abc1234def                                (optional)
**Skill**: https://raw.githubusercontent.com/.../skill.md  (optional, single URL)
```

## Proposed Ticket Format

```markdown
[Issue description — now also drives investigation strategy]

---
## Agent Configuration
**Repository**: https://github.com/org/repo          (REQUIRED)
**Branch**: main                                      (optional)
**Commit**: abc1234def                                (optional)
**Skills**:                                           (optional, multiple URLs)
  - https://raw.githubusercontent.com/org/ai-helpers/main/.claude/skills/go-conventions.md
  - https://raw.githubusercontent.com/org/ai-helpers/main/.claude/skills/api-patterns.md
  - https://raw.githubusercontent.com/org/ai-helpers/main/.claude/skills/testing-guide.md
**Knowledge Repo**: https://github.com/org/team-docs  (optional, cloned for context)
```

### Changes from Current Format

| Field | Current | Proposed |
|-------|---------|----------|
| `**Skill**:` | Single URL | **`**Skills**:`** — multiple URLs, bulleted list |
| `**Knowledge Repo**:` | N/A | New field — a separate repo cloned for domain context |
| Description text | Parsed for repo URL only | **Now analyzed for investigation signals** |

### Backward Compatibility

The old `**Skill**:` (singular) format is still accepted. If both
`**Skill**:` and `**Skills**:` are present, merge them into one list.

## Enhancement 1: Multiple Skills + Knowledge Repo

### Multiple Skill URLs

Allow the ticket to specify multiple skill URLs under `**Skills**:`.
Each URL is validated against the `skill_url_allowlist` in
`config/projects.json`. Non-matching URLs are logged as warnings
and skipped.

**Implementation in Phase 1 (Understand):**

```
1. Parse `**Skills**:` (plural) from description/comments
   - Accept bulleted list format (- URL per line)
   - Also accept old `**Skill**:` (singular) format
   - Merge both into a single list
   - Maximum 5 URLs (skip extras with warning)
2. For each URL in the list (sequential fetch):
   a. Validate against skill_url_allowlist patterns
   b. If valid: fetch with error handling:
      curl -sL --fail --max-time 30 --max-filesize 1048576 <url>
      (30s timeout, 1MB max size, fail on HTTP errors)
   c. If fetch returns non-200 or empty content: log warning, skip
   d. If invalid URL: log warning, skip
3. Provide all fetched skill content as additional context
   for Phases 3-5 (investigation, RCA, implementation)
```

**How skills are used:**

The fetched skills are NOT instructions — they are reference
material. The agent reads them for:
- Coding conventions and patterns specific to the repo/team
- Architecture context (how components interact)
- Testing strategies and frameworks used
- Known pitfalls or anti-patterns to avoid

The agent should treat skill content as **reference data** (same
trust level as the repo's CLAUDE.md), not as executable instructions
from the Jira ticket (which is untrusted).

### Knowledge Repo

A separate repository cloned alongside the target repo to provide
broader domain context: team documentation, architecture diagrams,
shared conventions, glossaries, etc.

**Implementation in Phase 2 (Prepare):**

```
1. Parse `**Knowledge Repo**:` from description/comments
2. Validate the URL against knowledge_repo_allowlist in projects.json
   (separate allowlist from skill URLs — explicit repo-level control)
3. If valid: shallow clone with hooks disabled and timeout:
   timeout 120 git clone --depth 1 --single-branch \
     --config core.hooksPath=/dev/null \
     <knowledge_repo_url> .knowledge/
4. Size check — if .knowledge/ exceeds 500MB, delete and skip:
   du -sm .knowledge/ | awk '{if ($1 > 500) exit 1}' || \
     (rm -rf .knowledge/ && echo "Knowledge repo too large, skipping")
5. If invalid, missing, timeout, or too large: skip (optional)
6. The agent can reference files in .knowledge/ during
   investigation and RCA
7. Clean up .knowledge/ after Phase 4B audit loop completes (or
   is skipped by the complexity gate), before Phase 5 begins.
   This ensures audit sub-agents can reference .knowledge/ during
   review if needed, while freeing disk before implementation.
```

**What the agent does with the knowledge repo:**

- Read ARCHITECTURE.md, GLOSSARY.md, CONVENTIONS.md if present
- Understand team terminology and component relationships
- Reference existing design decisions when planning a fix
- Check for documented anti-patterns before implementing
- NOT treated as the codebase being fixed — only as reference

**Security (ARCH-001 resolution):**
- Knowledge repo URL validated against a **separate** allowlist
  (`knowledge_repo_allowlist` in projects.json) — not the same
  wildcard as skill URLs
- Clone disables git hooks (`--config core.hooksPath=/dev/null`)
  to prevent arbitrary code execution from untrusted repos
- Clone has 2-minute timeout to prevent hanging on slow servers
- Size capped at 500MB to prevent disk exhaustion
- `.knowledge/` added to `.git/info/exclude`
- Cleaned up before Phase 5 (only needed during investigation)

### projects.json Update (PE-004 resolution — separate allowlist)

Skill URLs and knowledge repos use **separate** allowlists for
explicit security control:

```json
{
  "watched_projects": ["PROJ1", "PROJ2"],
  "skill_url_allowlist": [
    "https://raw.githubusercontent.com/org/*/main/.claude/skills/*",
    "https://raw.githubusercontent.com/org/*/.claude/skills/*"
  ],
  "knowledge_repo_allowlist": [
    "https://github.com/org/team-docs",
    "https://github.com/org/architecture-docs",
    "https://github.com/org/coding-standards"
  ],
  "bot_service_account": "bot-autofix"
}
```

The `knowledge_repo_allowlist` uses **exact repo URLs** (not
wildcards) to prevent cloning arbitrary repos. Teams must explicitly
register knowledge repos in the config.

## Enhancement 2: Signal-Driven Investigation Strategy

### Concept

Phase 3 (Investigate) currently uses a generic approach: grep for
keywords, read files, trace code paths. This enhancement adds a
**signal classification step** in Phase 1 that analyzes the issue
description using LLM reasoning (not keyword matching) and selects
a targeted investigation strategy for Phase 3.

### Signal Classification (ARCH-002 + AGENT-001 resolution)

**Placement:** End of Phase 1 (Understand), after parsing all ticket
fields. This is a classification step on already-parsed data, not an
investigation action.

**Method:** The agent uses its OWN reasoning to classify the issue —
NOT keyword regex matching. Keyword matching produces false positives
(e.g., "performance test" triggering Performance Strategy). The agent
reads the full description in context and classifies based on meaning.

**Classification prompt (internal reasoning):**

> Based on the issue description, classify this into at most 2 of
> these categories. Pick the PRIMARY signal first, then optionally
> a SECONDARY signal. If none match clearly, use "default".
>
> - **regression**: Something that previously worked now fails
> - **dependency**: Related to a package/library upgrade or version change
> - **concurrency**: Intermittent, timing-dependent, or race condition
> - **environment**: Works in one environment but not another
> - **performance**: Speed degradation, timeouts, resource exhaustion
> - **default**: None of the above, or unclear

**Output:** Primary signal + optional secondary signal. Maximum 2
strategies per ticket (AGENT-003 resolution — prevents wasting
investigation time on 3+ strategies).

| Signal | Strategy | When to Use |
|--------|----------|-------------|
| **regression** | Git History Strategy | Agent concludes something was working before and broke |
| **dependency** | Dependency Strategy | Agent concludes a package/library change is involved |
| **concurrency** | Concurrency Strategy | Agent concludes the issue is timing/ordering dependent |
| **environment** | Environment Strategy | Agent concludes behavior differs across environments |
| **performance** | Performance Strategy | Agent concludes the issue is about speed/resources |
| **default** | Default Strategy | Agent cannot confidently classify, or issue is generic |

### Strategy Execution Order (AGENT-003 resolution)

1. Always run the **default strategy first** (current grep + trace)
2. Then run the **primary signal strategy** for targeted investigation
3. If primary is inconclusive AND a secondary signal exists, run it
4. Maximum 2 specialized strategies per ticket

This inverts the risk: false signals ADD investigation on top of the
working default, rather than REPLACING it.

### Investigation Strategies

#### Git History Strategy (signal: regression)

When the description suggests something was working before:

```
1. Check recent commits on the affected branch:
   git log --oneline -20 --since="2 weeks ago"

2. If a specific timeframe is mentioned ("broke last Tuesday",
   "after PR #123"), narrow the log:
   git log --oneline --after="<date>" --before="<date>"

3. For each recent commit, check if it touches relevant files:
   git log --oneline --all -- <affected_file_paths>

4. If a suspect commit is found, analyze its diff:
   git show <commit_sha> -- <affected_files>

5. Use git blame on the affected lines:
   git blame -L <start>,<end> <file>

6. If the **Commit** field was provided in the ticket, analyze
   that specific commit as the primary suspect:
   git diff <commit>~1 <commit>

7. Consider git bisect if the regression range is identifiable:
   - Only if the agent can identify a "good" and "bad" commit
   - Run automated bisect with a test command if available
```

This strategy finds the root cause FAST for regressions because
it looks at what CHANGED, not what EXISTS.

#### Dependency Strategy (signal: upgrade/update)

When the description mentions a dependency change:

```
1. Check for recent changes to dependency files:
   git log --oneline -10 -- go.mod go.sum package.json
     package-lock.json pnpm-lock.yaml pyproject.toml
     requirements.txt Pipfile.lock pom.xml build.gradle

2. Diff the dependency file against the previous version:
   git diff HEAD~5 -- <lockfile>

3. Identify which dependencies changed and by how much:
   - Major version bump? Check for breaking changes
   - Minor/patch? Check changelogs for relevant fixes/regressions

4. Search for migration guides or breaking change notes:
   - Check the dependency's CHANGELOG.md or release notes
   - Look for deprecated API usage in the codebase

5. Focus investigation on code that uses the changed dependency:
   grep -rn "import.*<package>" --include="*.{go,py,ts,java}"
```

#### Concurrency Strategy (signal: intermittent/flaky)

When the description suggests timing-dependent behavior:

```
1. Search for concurrency primitives in affected code:
   - Go: goroutine, chan, sync.Mutex, sync.WaitGroup, context
   - Python: threading, asyncio, multiprocessing, Lock
   - Java: synchronized, volatile, CompletableFuture, ExecutorService
   - TypeScript: Promise, async/await, setTimeout, setInterval

2. Look for shared mutable state:
   - Global variables accessed by multiple threads/goroutines
   - Caches without synchronization
   - Database connections shared across requests

3. Check for race condition patterns:
   - Read-then-write without locking (check-then-act)
   - Missing context cancellation propagation
   - Unprotected map access in Go
   - Shared slice/array modification

4. Check for timing-dependent code:
   - Hardcoded timeouts or sleeps
   - Retry logic without backoff
   - Polling loops
   - Order-dependent initialization
```

#### Environment Strategy (signal: works locally but not in CI)

When the description suggests environment differences:

```
1. Compare CI and local configurations:
   - Read CI config files (.github/workflows/, .gitlab-ci.yml,
     Jenkinsfile, Tekton pipelines)
   - Check for env-specific config (dev vs staging vs prod)

2. Check for environment-dependent code:
   grep -rn "os.Getenv\|process.env\|os.environ" --include="*.{go,py,ts}"

3. Look for file path assumptions:
   - Absolute paths that differ between environments
   - Temp directory differences (/tmp vs /var/tmp vs Windows)

4. Check container/OS differences:
   - Dockerfile base image vs local OS
   - Library version differences
   - Filesystem case sensitivity (macOS vs Linux)

5. Check for network/connectivity assumptions:
   - Hardcoded hostnames or ports
   - DNS resolution differences
   - Proxy or firewall differences
```

#### Performance Strategy (signal: slow/timeout)

When the description mentions performance degradation:

```
1. Look for N+1 query patterns:
   - ORM queries in loops
   - Missing JOIN/eager loading

2. Check for unbounded operations:
   - Missing pagination on database queries
   - Unbounded in-memory collections
   - Recursive functions without depth limits

3. Look for missing caching:
   - Repeated expensive computations
   - Redundant API calls
   - Repeated database queries for the same data

4. Check for blocking operations in async paths:
   - Synchronous I/O in async handlers
   - Long-running operations without timeouts
   - Missing connection pool limits

5. Check recent changes that could affect performance:
   git log --oneline -10 -- <affected_paths>
```

#### Default Strategy (no signal detected)

Current behavior — grep for keywords, read relevant files, trace
code paths from symptom to cause. This is the fallback when no
specific signal is detected.

### Multiple Signals

If 2 signals are classified (e.g., primary=dependency,
secondary=concurrency for "intermittent failures after upgrading
the database driver"):

1. Run **default strategy first** (always)
2. Run **primary signal strategy**
3. If primary is inconclusive, run **secondary signal strategy**
4. Cross-reference findings across strategies
5. If strategies produce conflicting root causes, document both
   in the RCA and let the audit loop evaluate

### How Signals Interact with the Audit Loop (ARCH-004 resolution)

The detected signals and chosen strategy are included in the
**Fix Plan** (Phase 4A). The audit sub-agents review them:

- Architecture Reviewer: Is the chosen strategy appropriate for
  the signal detected? Did the agent miss a more relevant strategy?
- PE Reviewer: Does the fix address the root cause identified by
  the strategy, or just the symptom?
- Language Expert: Are the strategy-specific patterns (e.g.,
  concurrency primitives) handled idiomatically?

**Audit prompt files must be updated** to include strategy review
criteria (added to files-to-change list).

### How Signals Interact with the Complexity Gate (AGENT-004 resolution)

Signal type feeds into the complexity gate as an additional input:

| Signal | Complexity Floor | Rationale |
|--------|-----------------|-----------|
| **concurrency** | Single audit iteration minimum (rule 3) | Concurrency fixes are notoriously hard to get right |
| **performance** | Single audit iteration minimum (rule 3) | Performance changes have non-obvious side effects |
| **regression** with clear git-blame root cause | Can qualify for simple (rule 4) | Clear cause, minimal fix |
| **dependency** | Single audit iteration minimum (rule 3) | Breaking changes may have ripple effects |
| **environment** | No floor change | Typically config-only fixes |
| **default** | No floor change | Use existing gate logic |

This means a concurrency issue with a 1-file fix CANNOT skip audit
(the signal floors it at rule 3), even though the file/line count
alone would allow rule 4.

### Signal Detection in the Fix Plan

The fix plan (Phase 4A) includes a new section:

```markdown
### Investigation Strategy
**Signals detected**: regression ("was working before last deploy")
**Strategy used**: Git History Strategy
**Key findings from strategy**:
  - git log shows commit abc1234 (3 days ago) modified handler.go
  - git blame on affected line points to the same commit
  - The commit removed a null check that was previously present
```

This gives the audit sub-agents context about HOW the root cause
was found, not just what it is.

## Implementation Plan

### Phase 1: Multiple Skills + Knowledge Repo (Medium Effort)

Extend Phase 1 parsing for multi-skill + knowledge repo. Add
knowledge repo clone to Phase 2 with security controls.

**Files to change:**
- `workflows/issue-fix/skills/issue-fix.md` — Phase 1: multi-skill
  parsing + knowledge repo field. Phase 2: secure knowledge repo
  clone with hooks disabled, timeout, size limit, cleanup
- `config/projects.json` — add `knowledge_repo_allowlist`
- `README.md` — update ticket format

**Effort:** 25 min

### Phase 2: Signal-Driven Investigation (Medium Effort)

Add LLM-based signal classification to end of Phase 1. Extract 5
investigation strategies to a separate file (AGENT-002 resolution).
Add strategy reference to Phase 3 and fix plan schema.

**Files to change:**
- `workflows/issue-fix/skills/issue-fix.md` — Phase 1: add signal
  classification step (LLM reasoning, max 2 signals). Phase 3: add
  strategy execution order (default first, then primary, then
  secondary). Phase 4A: add Investigation Strategy to plan schema.
  Complexity gate: add signal-type floor rules.
- `workflows/issue-fix/skills/investigation-strategies.md` — NEW
  FILE: 5 strategy sections extracted from main skill to avoid
  1000+ line file
- `workflows/issue-fix/skills/audit-prompts/architecture.md` —
  add strategy review criteria (ARCH-004 resolution)

**Effort:** 45 min

### Phase 3: Documentation (Low Effort)

**Files to change:**
- `docs/Architecture.md` — document signal classification,
  multi-skill, knowledge repo, strategy-complexity gate interaction
- `docs/setup-and-testing.md` — add test scenarios
- `CLAUDE.md` — update ticket format documentation
- `README.md` — update ticket format (Skills plural, Knowledge Repo)

**Effort:** 20 min

## Files to Change

| File | Change | Effort |
|------|--------|--------|
| `workflows/issue-fix/skills/issue-fix.md` | Phase 1: multi-skill + knowledge repo + signal classification. Phase 2: secure knowledge repo clone. Phase 3: strategy execution. Phase 4A: plan schema update. Complexity gate: signal floor rules | 45 min |
| `workflows/issue-fix/skills/investigation-strategies.md` | NEW FILE: 5 investigation strategies (git history, dependency, concurrency, environment, performance) extracted from main skill. **Loading:** issue-fix.md Phase 3 includes explicit instruction: "Read skills/investigation-strategies.md from the workflow directory and follow the matching strategy." Same pattern as audit-prompts/ files. | 20 min |
| `workflows/issue-fix/skills/audit-prompts/architecture.md` | Add strategy review criteria: verify strategy matches signal, check for missed strategies | 5 min |
| `workflows/issue-fix/skills/audit-prompts/pe.md` | Add strategy review criteria: verify fix addresses root cause from strategy, not just symptom | 5 min |
| `workflows/issue-fix/skills/audit-prompts/language-expert.md` | Add strategy review criteria: verify strategy-specific patterns handled idiomatically | 5 min |
| `config/projects.json` | Add `knowledge_repo_allowlist` (exact repo URLs) | 2 min |
| `README.md` | Update ticket format (Skills plural, Knowledge Repo) | 10 min |
| `CLAUDE.md` | Update ticket format in cross-workflow docs | 5 min |
| `docs/Architecture.md` | Document signal classification, multi-skill, knowledge repo, strategy-complexity gate interaction | 15 min |
| `docs/setup-and-testing.md` | Add test scenarios (regression signal, multi-skill, knowledge repo) | 10 min |

## Open Questions

**Resolved by audit Round 1:**
- ~~Signal detection method?~~ → LLM reasoning, not keyword matching
- ~~Where does signal detection go?~~ → End of Phase 1 (classification)
- ~~How many strategies per ticket?~~ → Max 2 (primary + secondary)
- ~~Max skill URLs?~~ → 5, enforced in parsing
- ~~Per-ticket Audit override?~~ → Removed, deferred to v2
- ~~Knowledge repo security?~~ → Hooks disabled, timeout, size cap,
  separate allowlist with exact URLs

**Still open:**
- [ ] Should signal classification be reported explicitly in Jira
      ("Signal detected: regression") or just in the fix plan?
- [ ] Should the knowledge repo be accessible to audit sub-agents?
      (current answer: no — cleaned up before Phase 5, only available
      during investigation)
- [ ] Should the watcher validate knowledge repo / skill URLs and
      pass them through the session prompt (trusted path) instead of
      the fix agent re-parsing from Jira?

## Acceptance Criteria

### Multiple Skills
- [ ] `**Skills**:` (plural, bulleted list) parsed in Phase 1
- [ ] Old `**Skill**:` (singular) still works (backward compatible)
- [ ] Each URL validated against skill_url_allowlist
- [ ] Invalid URLs logged as warnings, skipped (not blocking)
- [ ] All valid skills fetched and available as context for Phases 3-5
- [ ] Skill content treated as reference data, not executable instructions

### Knowledge Repo
- [ ] `**Knowledge Repo**:` parsed in Phase 1
- [ ] URL validated against knowledge_repo_allowlist (NOT skill_url_allowlist)
- [ ] Shallow clone to `.knowledge/` in Phase 2
- [ ] `.knowledge/` added to `.git/info/exclude`
- [ ] Agent references .knowledge/ files during investigation/RCA
- [ ] If URL invalid or missing: skip without error

### Signal-Driven Investigation
- [ ] Signal classification runs at end of Phase 1 using LLM reasoning
      (not keyword matching)
- [ ] Maximum 2 signals classified (primary + optional secondary)
- [ ] 5 strategies extracted to `skills/investigation-strategies.md`
- [ ] Execution order: default FIRST, then primary, then secondary
      (if primary inconclusive)
- [ ] Default strategy (current behavior) always runs
- [ ] Investigation strategy documented in Phase 4A fix plan
- [ ] Audit sub-agents (architecture.md) updated with strategy
      review criteria
- [ ] Signal type feeds complexity gate: concurrency/performance/
      dependency floor at single audit iteration minimum
