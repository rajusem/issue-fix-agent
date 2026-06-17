# Architecture Review Findings — Cross-Project Analysis

> Generated: 2026-06-05 | Priority review: 2026-06-05
> Source: Deep-dive comparison of issue-fix-agent against all 13 sibling
> projects in `2026_05_issue_fix_agent_work/` (including template-agent)
> Status: Sprint 1 DONE. Remaining items are domain requirements —
> implementation approach changes with OpenCode + OpenShell migration
> (see `docs/plan-opencode-openshell-migration.md`).

---

## Already Implemented (from prior TODO docs)

These features are already in the skill files — not re-prioritized:

| Feature | TODO Doc | Implemented In |
|---------|----------|---------------|
| Audit loop (3 sub-agents) | `TODO-design-audit-rounds.md` | `issue-fix.md` Phase 4A/4B |
| RTK token optimization | `TODO-rtk-integration.md` | `issue-fix.md` Phase 1/4B/10 |
| Signal-driven investigation | `TODO-smart-context-investigation.md` | `issue-fix.md` Phase 1/3 |
| Cost telemetry footers | `TODO-cost-telemetry.md` | `issue-fix.md` Phase 10 |
| Complexity gate w/ signal floors | `TODO-design-audit-rounds.md` | `issue-fix.md` Complexity Gate |
| Multi-skill + knowledge repo | `TODO-smart-context-investigation.md` | `issue-fix.md` Phase 1/2 |
| TTL-aware checkpoints | `TODO-design-audit-rounds.md` | `issue-fix.md` Phase 4B |

---

## Priority Matrix — PE + Agent Expert Review

**MVP scope:** Staging demo on OBSINTA, internal reporters only, known test
repo, gitleaks not in container image.

### Sprint 1: MVP NEEDED — DONE

**Commit**: `93265d5` | **Plan doc**: `docs/plans/UNTRACKED/mvp-security-hardening.md`
**Audited**: 2 rounds (architecture, PE, SDLC, agent expert) — approved after revisions

| # | Item | Status |
|---|------|--------|
| 1.6 | Sensitive File Blocklist | DONE — specific patterns, basename matching, set -f + process substitution |
| 1.8 | Git Security Hardening | DONE — unconditional hooksPath/fsmonitor, protocol restrictions on all clones |
| 1.9 | Repo URL Validation | DONE — full check in watcher, lightweight in all child workflows, fail-closed |
| 2.8 | Preflight Env Checks | DONE — `gh api user` + `git --version` in Phase 0 |
| 1.10 | No-Autofix Opt-Out | DONE — JQL, CLAUDE.md, README.md |

**Additional items from label lifecycle audit (committed separately):**

**Commit**: `e046a43` | **Plan doc**: `docs/plans/UNTRACKED/label-lifecycle-fixes.md`
**Audited**: 4 rounds x 4 independent reviewers — all approved in Round 4

| # | Item | Status |
|---|------|--------|
| NEW | bot-missing-info auto-recovery (Phase 7) | DONE — header whitelist filter, staleness reminder |
| NEW | bot-retry label (Phase 8) | DONE — MAX_FIX_RETRIES=2, Retry Context in fix agent |
| NEW | Closed PR detection (Phase 4 step 5) | DONE — closed-not-merged → bot-fix-failed |
| NEW | Label swap verification protocol | DONE — verify + retry + transient failure handling in all 4 workflows |
| NEW | bot-cancelled human override (Phase 5) | DONE — before stale cleanup, removes bot-retry |
| NEW | TTL awareness for watcher | DONE — config-var checkpoint, skip to summary if < 3 min |
| NEW | Cross-workflow contracts table update | DONE — 4 new headers in CLAUDE.md |

---

### Sprint 2: MVP GOOD-TO-HAVE (~2 hours)

Improves staging quality and efficiency. Implement before showing to
stakeholders.

| # | Item | Effort | PE Rationale | Agent Expert Rationale |
|---|------|--------|-------------|----------------------|
| 1.3 | **Embargo Filter** | 5m | One JQL clause. Trivial effort, prevents accidental processing of pre-disclosure security tickets | Zero risk to add. Not likely in staging observability project but protects against edge case |
| 1.5 | **Bot Comment Filtering** | 15m | On retry, agent re-reads 5-10 of its own prior comments. Wastes tokens but doesn't cause incorrect behavior | Bot comments can confuse model (sees prior `## Fix Applied`, thinks PR exists). Sentinel phrase filtering is straightforward |
| 1.1 | **Comment Domain Filtering** | 20m | No external commenters in staging OBSINTA. Attack surface is zero in this environment | Establishes the pattern early. Good practice even when not strictly needed |
| 2.2 | **State Persistence** | 30-45m | 150m TTL sessions WILL hit context compression. `.audit/approved-plan.md` partially covers it but agent loses phase/ticket/branch state | Difference between robust pipeline and one that wastes 30+ min redoing work after compression. Manual monitoring catches issues in staging |
| 2.3 | **Pipeline Health Diagnostics** | 15m | Tickets can silently get stuck in `bot-in-progress`. Enriching Slack summary with label counts gives at-a-glance health | Low effort enhancement to existing Slack notification. Useful even for staging monitoring |
| 2.7 | **Structured Verdict Schema** | 15m | Missing fields cause Phase 10 telemetry footer to render incorrectly. Cosmetic in staging | Schema definition ensures consistent reporting. Useful for later aggregation |

**Implementation order:** 1.3 → 1.5 → 1.1 → 2.2 → 2.3 → 2.7
**Dependency:** 1.1 establishes domain filter pattern used by 1.2 and 1.4 later.

---

### Sprint 3: PRODUCTION NEEDED (~1-2 days)

Must have before opening to real teams with real tickets.

| # | Item | Effort | PE Rationale | Agent Expert Rationale |
|---|------|--------|-------------|----------------------|
| 1.2 | **Label Author Verification** | 20-30m | Anyone with label permissions can trigger $5-20 Opus sessions. Cost-amplification vector in production | Prevents unauthorized bot activation. Requires Jira changelog API (test MCP vs REST fallback) |
| 1.4 | **External Reporter Gate** | 15m | Production Jira has external reporters. Adversarial descriptions are the primary prompt injection vector | Filtering by reporter domain prevents agent from operating on tickets designed to exploit it |
| 1.7 | **Gitleaks Secret Scanning** | 10m+img | Entropy-based detection catches API keys and tokens that filename patterns (1.6) cannot. Requires container image update | Degrade gracefully (warn if gitleaks missing). Skill change is 10m; container image is separate work |
| 2.1 | **Triage Pre-Screening** | 1-2h | 20-40% of production tickets will be unfixable. Each burns $5-20 in Opus. 10m Sonnet triage ($0.30) filters them out. At 20 tickets/day: saves $20-160/day | 3-gate rubric (can start? can find? should fix?) is proven in autofix-skills. Prevents 60+ min wasted on fundamentally unfixable tickets |
| 2.4 | **CI-Failing Label** | 30m | `bot-review-fix` conflates code review findings and CI failures. Different fix strategies needed | Review agent already runs `gh pr checks`. Label branch lets review-fix choose right strategy |
| 2.6 | **Prior Review Context** | 20m | Blind re-review on cycle 2/3 may re-report fixed findings (false alarm) or miss fix-introduced regressions | Data already flows through `## Agent Code Review` Jira comments. Just needs smarter re-read logic |
| 3.3 | **LLM Observability** | 1-2h | No token-level cost tracking. Duration ≠ cost. Production needs actual token counts for budget alerts | Langfuse is in the Ambient Platform already. Enables identifying expensive strategies and validating RTK savings |
| 3.13 | **OpenShift Manifests** | 2-3h | Production needs reproducible deployment with liveness/readiness probes, resource limits, secrets management | Not agent quality — infrastructure requirement for production existence |

**Implementation order:** 1.2 → 1.4 → 1.7 → 2.4 → 2.6 → 2.1 → 3.3 → 3.13
**Dependencies:** 1.4 depends on 1.1 (domain filter pattern). 2.1 is a new
workflow. 3.13 needs finalized config.

---

### Sprint 4+: PRODUCTION GOOD-TO-HAVE (ongoing)

Maturity features. Prioritize based on observed production pain points.

| # | Item | Effort | When to prioritize |
|---|------|--------|--------------------|
| 2.5 | Two-Agent Parallel Review | 1-2h | If Sonnet security review misses subtle vulns |
| 3.5 | Structural Sweep | 1h | If reviews miss coverage on large PRs |
| 3.9 | Verification Results Table | 30m | If review false-positive rate is high |
| 3.2 | Extension Points | 1h | When multiple teams want custom validation |
| 3.4 | Deep Verification Agent | 2-3h | For concurrency/security fixes specifically |
| 3.10 | Score Trajectory | 20m | After 2.6 (prior review context) is done |
| 3.1 | Orchestrator/Worker Separation | Days | If context exhaustion is a common failure |
| 3.7 | Research/Spike Skill | 1-2h | If triage (2.1) routes many to "needs investigation" |
| 3.6 | Domain-Specific Reviewers | Hours/domain | For repos with complex concurrency or ORM |
| 3.8 | CVE Remediation Workflow | Hours | When CVE tickets are labeled autofix |
| 3.11 | Post-Merge Feedback Loop | 1-2h | After enough merged PRs for statistical signal |
| 3.12 | Python Orchestrator (LangGraph) | Days | Only if skill-based approach hits fundamental limits |

---

## Detailed Item Descriptions

The sections below contain full implementation plans, code examples, source
references, and file lists for each item. Items are numbered by their
original theme grouping (1.x = security, 2.x = operational, 3.x = architecture)
but should be implemented in the sprint order above.

---

## Phase 1: Security Hardening (Before First Production Run)

These gaps represent real attack vectors that sibling projects (`agentic-ci`,
`autofix`) already defend against. All are low effort.

---

### 1.1 Comment Domain Filtering

**Status:** TODO
**Priority:** CRITICAL
**Source:** `agentic-ci/src/agentic_ci/gates.py:214-219`
**Affects:** `issue-fix` skill (Phase 1), `review-fix` skill (Phase 2)

**Problem:** Our agents parse ALL Jira comments without filtering. An
external actor with comment access can inject malicious content (prompt
injection, fake reproduction steps, misleading error messages) that the
agent will treat as trusted context.

**Solution from agentic-ci:**
```python
def filter_comments_by_domain(
    comments: list[dict],
    allowed_domain_re: re.Pattern[str],
) -> list[dict]:
    return [c for c in comments if allowed_domain_re.search(c.get("author_email", ""))]
```
`autofix` uses `_REDHAT_EMAIL_RE = re.compile(r"@redhat\.com$", re.IGNORECASE)`.

**Implementation plan:**
1. Add comment filtering to the **watcher** skill (Phase 1 ticket parsing) —
   when extracting agent configuration fields from comments, only consider
   comments from `@redhat.com` authors
2. Add comment filtering to the **issue-fix** skill (Phase 1 Understand) —
   when reading ticket comments for context, filter to internal domain
3. Add comment filtering to the **review-fix** skill (Phase 1 Fetch Context) —
   when reading Jira comments for PR URL and review findings
4. Add a `comment_domain_filter` field to `config/projects.json`:
   ```json
   "comment_domain_filter": "@redhat\\.com$"
   ```
5. The watcher passes this pattern to child sessions in the prompt context

**Exception:** Bot's own structured comments (`## Fix Applied`, `## Agent
Code Review`, etc.) should always be readable regardless of author domain,
since the bot service account may not have a @redhat.com email. Filter by
domain for free-text context, but always parse structured `## ` headers
from any author matching `bot_service_account` in projects.json.

**Files to modify:**
- `workflows/jira-watcher/skills/jira-watcher.md` — Phase 1 ticket parsing
- `workflows/issue-fix/skills/issue-fix.md` — Phase 1 Understand
- `workflows/issue-review/skills/issue-review.md` — Phase 1 Fetch Context
- `workflows/review-fix/skills/review-fix.md` — Phase 1 Fetch Context
- `config/projects.json` — add `comment_domain_filter` field

---

### 1.2 Label Author Verification

**Status:** TODO
**Priority:** CRITICAL
**Source:** `autofix/src/jira_autofix/gates/pre_agent.py:48-50`
**Affects:** `jira-watcher` skill (Phase 1)

**Problem:** Anyone who can add labels to a Jira ticket can trigger the bot
by adding the `autofix` label. This is a privilege escalation vector —
external contributors or compromised accounts could trigger expensive Opus
sessions against arbitrary repositories.

**Solution from autofix:**
```python
def check_label_author_redhat(author_info: dict) -> bool:
    return check_label_author_email(author_info, _REDHAT_EMAIL_RE)
```
Uses the Jira changelog API to find who added the `autofix` label and
verifies their email matches `@redhat.com`.

**Implementation plan:**
1. In the watcher's Phase 1, after finding a ticket with `autofix` label:
   a. Fetch the ticket's changelog (may need Jira REST API — check if
      `mcp__atlassian__getJiraIssue` returns changelog/history)
   b. Find the changelog entry where `autofix` label was added
   c. Verify the author's email matches `comment_domain_filter`
   d. If verification fails or changelog is inaccessible:
      - Add `bot-missing-info` label
      - Post comment: "The `autofix` label must be added by an internal
        team member. Label author could not be verified."
      - Skip this ticket
2. If MCP doesn't expose changelog, fall back to REST API:
   ```bash
   curl -s "https://$JIRA_SITE/rest/api/3/issue/<KEY>?expand=changelog" \
     -u "$JIRA_USERNAME:$JIRA_API_TOKEN"
   ```

**Files to modify:**
- `workflows/jira-watcher/skills/jira-watcher.md` — Phase 1, after JQL query

---

### 1.3 Embargo Filter

**Status:** TODO
**Priority:** HIGH
**Source:** `autofix/src/jira_autofix/labels.py:49-51`
**Affects:** `jira-watcher` skill (Phase 1, 2, 3 JQL queries)

**Problem:** The watcher will pick up embargoed security tickets that should
never be processed by automation. Embargoed tickets may contain pre-disclosure
vulnerability details that should not be exposed to AI systems or committed
to branches before the embargo lifts.

**Solution from autofix:**
```python
EMBARGO_FILTER = (
    'summary !~ "EMBARGOED" AND (level IS EMPTY OR level != "Embargoed Security Issue")'
)
```

**Implementation plan:**
1. Add the embargo filter to ALL JQL queries in the watcher skill:
   - Phase 1 (new autofix tickets)
   - Phase 2 (review dispatch)
   - Phase 3 (review-fix dispatch)
   - Phase 4 (post-merge)
2. Add to `config/config.env`:
   ```
   EMBARGO_FILTER='summary !~ "EMBARGOED" AND (level IS EMPTY OR level != "Embargoed Security Issue")'
   ```

**Files to modify:**
- `workflows/jira-watcher/skills/jira-watcher.md` — all JQL queries
- `config/config.env` — add EMBARGO_FILTER

---

### 1.4 External Reporter Gate

**Status:** TODO
**Priority:** HIGH
**Source:** `autofix/src/jira_autofix/gates/pre_agent.py:53-59`
**Affects:** `jira-watcher` skill (Phase 1)

**Problem:** Tickets from external reporters (non-@redhat.com) could contain
adversarial content designed to exploit the AI agent. External reporters
may also file tickets that reference repositories outside the team's control.

**Solution from autofix:**
```python
def check_external_reporter(ticket: dict) -> str | None:
    reporter_email = ticket.get("reporter_email", "")
    labels = ticket.get("labels", [])
    if TRIAGE_EXTERNAL in labels:
        return None  # already flagged
    if not _REDHAT_EMAIL_RE.search(reporter_email):
        return TRIAGE_EXTERNAL
    return None
```

**Implementation plan:**
1. In the watcher's Phase 1, after fetching a ticket:
   a. Check the reporter's email against the internal domain filter
   b. If external:
      - Add `bot-external-reporter` label
      - Post comment:
        ```
        ## External Reporter
        This ticket was opened by an external reporter. An internal team
        member must review and add the `bot-external-approved` label
        before the agent will process it.
        ```
      - Skip this ticket
   c. Allow processing if `bot-external-approved` label is present
2. Add `bot-external-reporter` and `bot-external-approved` to the label
   state machine documentation

**New labels:**
- `bot-external-reporter` — ticket from external reporter, needs internal review
- `bot-external-approved` — internal team approved external ticket for bot processing

**Files to modify:**
- `workflows/jira-watcher/skills/jira-watcher.md` — Phase 1
- `CLAUDE.md` — label state machine
- `README.md` — label table

---

### 1.5 Bot Comment Filtering

**Status:** TODO
**Priority:** HIGH
**Source:** `autofix/src/jira_autofix/labels.py:55-60`
**Affects:** `issue-fix` skill, `review-fix` skill

**Problem:** When the agent re-reads ticket comments (e.g., on retry, or
during review-fix), it sees its own prior structured comments (`## Fix
Applied`, `## Agent Session Started`, milestone comments). These waste
context tokens and can create feedback loops where the agent responds to
its own prior output.

**Solution from autofix:**
```python
NO_REPO_URL_MSG = "Could not find a repository URL..."
EXTERNAL_REPORTER_MSG = "This ticket was opened by an external reporter..."

def filter_bot_comments(comments, sentinel_phrases):
    return [c for c in comments if not any(s in c.get("body", "") for s in sentinel_phrases)]
```

**Implementation plan:**
1. Define sentinel phrases for bot comments:
   - "Agent started working on this ticket"
   - "## Agent Session Started"
   - "## Missing Information"
   - "## Audit — Iteration"
   - "## Fix Plan (v"
   - "RCA complete. Root cause:"
   - "Branch `" (milestone comment)
   - "Tests passing." (milestone comment)
   - "RTK token optimization enabled"
2. When reading ticket comments for context (not for structured data
   extraction), filter out comments containing any sentinel phrase
3. Keep structured comments (`## Fix Applied`, `## Agent Code Review`)
   accessible for cross-workflow contract parsing — those are data, not
   noise

**Files to modify:**
- `workflows/issue-fix/skills/issue-fix.md` — Phase 1
- `workflows/review-fix/skills/review-fix.md` — Phase 1

---

### 1.6 Sensitive File Blocklist

**Status:** TODO
**Priority:** HIGH
**Source:** `agentic-ci/src/agentic_ci/gates.py:91-119`
**Affects:** `issue-fix` skill (Phase 6 Pre-PR Checks)

**Problem:** Our pre-PR self-review says "no secrets, no debug code" but
relies on the agent's judgment to catch sensitive files. There's no
deterministic blocklist.

**Solution from agentic-ci:**
```python
DEFAULT_SENSITIVE_BLOCKLIST = [
    ".env",
    "credentials.*",
    "*secret*",
    "*.pem",
    "*.key",
    ".git-credentials",
    ".netrc",
]

def check_sensitive_files(changed_files, blocklist=None):
    if blocklist is None:
        blocklist = DEFAULT_SENSITIVE_BLOCKLIST
    blocked = []
    for filepath in changed_files:
        name = Path(filepath).name
        for pattern in blocklist:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(filepath, pattern):
                blocked.append(filepath)
                break
    return blocked
```

**Implementation plan:**
1. Add a deterministic sensitive file check to Phase 6 (Pre-PR Checks):
   ```bash
   # Check changed files against blocklist
   BLOCKED_PATTERNS=".env credentials.* *secret* *.pem *.key .git-credentials .netrc *.p12 *.pfx"
   for pattern in $BLOCKED_PATTERNS; do
     git diff --cached --name-only | while read f; do
       if [[ "$(basename "$f")" == $pattern ]]; then
         echo "BLOCKED: $f matches sensitive pattern $pattern"
         # Unstage and abort
       fi
     done
   done
   ```
2. If any blocked file is staged: unstage it, log a warning, and verify
   the fix still works without it. If the blocked file is essential to the
   fix (e.g., updating a `.env.example`), the file name patterns should be
   configurable.
3. Add `sensitive_file_blocklist` to `config/projects.json` for
   project-specific overrides.

**Files to modify:**
- `workflows/issue-fix/skills/issue-fix.md` — Phase 6
- `workflows/review-fix/skills/review-fix.md` — Phase 6
- `config/projects.json` — optional blocklist override

---

### 1.7 Gitleaks Secret Scanning

**Status:** TODO
**Priority:** HIGH
**Source:** `agentic-ci/src/agentic_ci/gates.py:147-208`
**Affects:** `issue-fix` skill (Phase 6), `review-fix` skill (Phase 6)

**Problem:** No automated secret scanning before pushing commits. Relies
entirely on the agent's ability to notice secrets in its own output.

**Solution from agentic-ci:**
```python
def gitleaks_scan(repo_dir, compare_ref="origin/HEAD"):
    if not shutil.which("gitleaks"):
        return ["gitleaks is not installed; secret scan cannot run"]  # fail closed
    result = subprocess.run(
        ["gitleaks", "detect", "--source", str(repo_dir),
         f"--log-opts={compare_ref}..HEAD", "--verbose"],
        capture_output=True, text=True, timeout=GITLEAKS_TIMEOUT,
    )
    if result.returncode != 0:
        return ["gitleaks detected potential secrets..."]
    return []
```

Key design: **fail closed** — if gitleaks is not installed or times out,
the scan fails rather than silently passing.

**Implementation plan:**
1. Add gitleaks scan to Phase 6 (Pre-PR Checks) after staging files:
   ```bash
   # Secret scan — fail closed
   if which gitleaks >/dev/null 2>&1; then
     gitleaks detect --source . --log-opts="origin/HEAD..HEAD" --verbose
     if [ $? -ne 0 ]; then
       echo "BLOCKED: gitleaks detected potential secrets"
       # Follow failure protocol
     fi
   else
     echo "WARNING: gitleaks not installed — secret scan skipped"
     # Record in .audit/validation.json: gitleaks_scan: "skipped"
   fi
   ```
2. Record result in `.audit/validation.json`:
   - `gitleaks_scan`: "passed" / "failed" / "skipped" / "timed_out"
3. If gitleaks is not available, log warning but proceed (Ambient images
   may not have gitleaks pre-installed — add to future container image)
4. Add gitleaks to the Ambient container image requirements

**Dependency:** Requires `gitleaks` binary in the Ambient session container.
If not available, degrade gracefully (warn, don't block).

**Files to modify:**
- `workflows/issue-fix/skills/issue-fix.md` — Phase 6
- `workflows/review-fix/skills/review-fix.md` — Phase 6

---

### 1.8 Git Security Hardening

**Status:** TODO
**Priority:** HIGH
**Source:** `agentic-ci/src/agentic_ci/git.py:353-365, 142-151, 154-189`
**Affects:** `issue-fix` skill (Phase 2 Prepare), `review-fix` skill (Phase 3)

**Problem:** When the agent clones a target repo, malicious git hooks in
that repo could execute arbitrary code. We also don't validate branch names
or ref names against injection attacks.

**Solution from agentic-ci:**

Git config hardening:
```python
def harden_git_config(repo_dir):
    for key, value in [
        ("core.hooksPath", "/dev/null"),   # disable git hooks
        ("core.fsmonitor", "false"),        # disable fsmonitor
    ]:
        subprocess.run(["git", "config", key, value], cwd=str(repo_dir), ...)
```

Ref validation:
```python
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9._/\-~^]+$")

def _validate_ref(name):
    if not name or name.startswith("-"):
        return False
    if ".." in name or "@{" in name:
        return False
    return bool(_SAFE_REF_RE.match(name))
```

Clone with protocol restrictions:
```python
cmd = ["git", "-c", "protocol.ext.allow=never",
       "-c", "protocol.file.allow=never", "clone", ...]
```

**Implementation plan:**
1. In Phase 2 (Prepare), after cloning or detecting the repo:
   ```bash
   # Harden git config — prevent malicious hooks
   git config core.hooksPath /dev/null
   git config core.fsmonitor false
   ```
2. Validate branch names before `git checkout -b`:
   ```bash
   # Reject branches starting with - or containing .. or @{
   if [[ "$BRANCH" == -* ]] || [[ "$BRANCH" == *..* ]] || [[ "$BRANCH" == *@{* ]]; then
     echo "ERROR: Invalid branch name"
     # Follow failure protocol
   fi
   ```
3. If the agent clones manually (not via Ambient `repos` field), use
   protocol restrictions:
   ```bash
   git -c protocol.ext.allow=never -c protocol.file.allow=never \
     clone -- <repo_url> work
   ```

**Files to modify:**
- `workflows/issue-fix/skills/issue-fix.md` — Phase 2
- `workflows/review-fix/skills/review-fix.md` — Phase 3

---

### 1.9 Repo URL Validation

**Status:** TODO
**Priority:** HIGH
**Source:** `agentic-ci/src/agentic_ci/git.py:126-139`
**Affects:** `jira-watcher` skill (Phase 1), `issue-fix` skill (Phase 1)

**Problem:** We parse the `**Repository**:` field from the Jira ticket and
use it directly without validation. A malicious URL could:
- Point to a non-HTTPS host (e.g., `file://` or `ssh://`)
- Contain credentials in the URL (`https://user:pass@...`)
- Use path traversal (`../../../etc/passwd`)
- Point to an internal/unallowed host

**Solution from agentic-ci:**
```python
ALLOWED_HOSTS = frozenset({"github.com", "gitlab.com"})

def validate_repo_url(url):
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    if not parsed.hostname or parsed.hostname not in ALLOWED_HOSTS:
        return False
    if parsed.username or parsed.password:
        return False
    if ".." in (parsed.path or ""):
        return False
    return True
```

**Implementation plan:**
1. Add `allowed_repo_hosts` to `config/projects.json`:
   ```json
   "allowed_repo_hosts": ["github.com", "gitlab.com", "gitlab.cee.redhat.com"]
   ```
2. In the watcher's Phase 1, validate the extracted repo URL:
   - Must be HTTPS
   - Host must be in `allowed_repo_hosts`
   - No credentials in URL
   - No `..` in path
3. If validation fails, treat as missing info (add `bot-missing-info`)

**Files to modify:**
- `workflows/jira-watcher/skills/jira-watcher.md` — Phase 1
- `workflows/issue-fix/skills/issue-fix.md` — Phase 1 entry gates
- `config/projects.json` — add `allowed_repo_hosts`

---

### 1.10 No-Autofix Opt-Out Label

**Status:** TODO
**Priority:** MEDIUM
**Source:** `autofix/src/jira_autofix/labels.py:22`
**Affects:** `jira-watcher` skill (Phase 1 JQL)

**Problem:** No way for teams to exclude specific tickets from bot
processing. If a ticket is tagged `autofix` but the team later decides it
shouldn't be automated, they have to remove the `autofix` label (which
loses the intent marker).

**Solution from autofix:**
```python
LABEL_OPT_OUT = "no-autofix"
```

**Implementation plan:**
1. Add `no-autofix` to the JQL exclusion in Phase 1:
   ```
   AND labels NOT IN (..., no-autofix)
   ```
2. Document in README: "Add `no-autofix` to exclude a ticket from
   automation while keeping the `autofix` label for tracking."

**Files to modify:**
- `workflows/jira-watcher/skills/jira-watcher.md` — Phase 1 JQL
- `README.md` — label table
- `CLAUDE.md` — label state machine

---

## Phase 2: Operational Maturity (After First 5-10 Tickets)

These improve reliability, efficiency, and observability. Not
security-critical but will become pain points quickly.

---

### 2.1 Triage Pre-Screening

**Status:** TODO
**Priority:** HIGH
**Source:** `autofix-skills/skills/autofix-triage/SKILL.md`
**Affects:** New workflow: `workflows/issue-triage/`

**Problem:** Every ticket with `autofix` label gets an expensive Opus
session (60-150m, high token cost). Many tickets are unfixable — missing
context, architectural issues, external dependencies, infrastructure
problems. A cheap Sonnet triage step could filter these out.

**Design from autofix-skills:**
Three-gate rubric with "bias toward ready when uncertain":

- **Gate 1 — Can the Agent Start?** Repo URL exists, ticket states what
  is broken (not just "it's broken").
- **Gate 2 — Can the Agent Find and Fix It?** Code is locatable (file
  paths, error messages, component names), correct behavior is unambiguous.
- **Gate 3 — Should an Agent Fix This?** Not blocked by: design decisions,
  infrastructure, external deps, runtime-only diagnosis, performance
  tuning, non-code fixes.

Verdict: `ready` / `needs_info` / `not_fixable`
Calibration: "A wasted autofix cycle is far cheaper than a false rejection."

**Implementation plan:**
1. Create new workflow: `workflows/issue-triage/`
   - `ambient.json`, `CLAUDE.md`, `skills/issue-triage.md`
   - Model: Sonnet (cheap, fast)
   - TTL: 10 minutes
2. Modify watcher Phase 1 flow:
   ```
   autofix ticket found
     → dispatch triage session (Sonnet, 10m)
     → if ready: add bot-in-progress, dispatch fix session
     → if needs_info: add bot-missing-info, post what's needed
     → if not_fixable: add bot-not-fixable, post why
   ```
3. Add new label: `bot-not-fixable`
4. The triage agent writes its verdict as a Jira comment:
   ```
   ## Triage Verdict
   **Result**: ready / needs_info / not_fixable
   **Confidence**: HIGH / MEDIUM / LOW
   **Gate 1**: PASS / FAIL — <reason>
   **Gate 2**: PASS / FAIL — <reason>
   **Gate 3**: PASS / FAIL — <reason>
   ```

**Trade-off:** Adds latency (one Sonnet session before the Opus session).
But prevents wasting $5-20 per unfixable ticket. Net positive if even 20%
of tickets are unfixable.

**New files:**
- `workflows/issue-triage/ambient.json`
- `workflows/issue-triage/CLAUDE.md`
- `workflows/issue-triage/skills/issue-triage.md`
- `config/config.env` — TRIAGE_MODEL, TRIAGE_SESSION_TTL

---

### 2.2 State Persistence for Context Compression Recovery

**Status:** TODO
**Priority:** HIGH
**Source:** `autofix-skills/scripts/state.py`
**Affects:** `issue-fix` skill (all phases)

**Problem:** Long-running Opus sessions (60-150m) WILL hit context
compression. When context compresses, the agent loses track of:
- Which phase it's in
- What the ticket key is
- How many audit iterations have run
- What the approved plan looks like
- Whether RTK was active

Without state persistence, the agent either starts over (wasting time) or
makes incorrect assumptions about where it left off.

**Solution from autofix-skills:**
```python
# state.py provides:
#   init <file>               — create initial state
#   get <file> <key>          — read value
#   set <file> <key> <value>  — write value
#   dispatch-context <file>   — print recovery instructions

# SessionStart hook calls dispatch-context after compression:
# It prints: "NEXT: Call the implement agent (iteration 2)"
```

State file is YAML on disk (survives compression). A `dispatch-recovery.sh`
script is generated at init time and registered as a SessionStart hook.

**Implementation plan:**
1. Create `scripts/state.py` (adapt from autofix-skills version):
   - Track: phase, ticket_key, branch, iteration, rtk_active, plan_version,
     start_time, signal_classification, pr_url
   - `dispatch-context` prints phase-specific recovery instructions
2. Add state initialization to Phase 1:
   ```bash
   python3 scripts/state.py init .fix-state.yaml
   python3 scripts/state.py set .fix-state.yaml ticket_key <KEY>
   ```
3. Update state at each phase transition:
   ```bash
   python3 scripts/state.py set .fix-state.yaml phase "Phase 5: Implement"
   ```
4. Register SessionStart hook (if Ambient supports it) or add recovery
   instructions to the CLAUDE.md:
   ```
   If you find .fix-state.yaml in the workspace, run:
   python3 scripts/state.py dispatch-context .fix-state.yaml
   ```

**New files:**
- `scripts/state.py`

**Files to modify:**
- `workflows/issue-fix/skills/issue-fix.md` — all phase transitions
- `workflows/issue-fix/CLAUDE.md` — context recovery instructions

---

### 2.3 Pipeline Health Diagnostics

**Status:** TODO
**Priority:** MEDIUM
**Source:** `autofix/src/jira_autofix/diagnose.py`
**Affects:** `jira-watcher` skill (new Phase 6 or separate workflow)

**Problem:** No way to know if the pipeline is healthy. Tickets could be
stuck in `bot-in-progress` for days without anyone noticing. No dashboard
of ticket counts by label state.

**Solution from autofix:**
```python
def diagnose(config_path):
    # Count tickets by each label state
    for name, label in AUTOFIX_LABELS.items():
        tickets = _count_by_label(projects, label)
        print(f"  {name:15s} {count:4d}")

    # Find orphaned tickets (stuck > 4h)
    orphaned = _find_orphaned_pending(projects)
    if orphaned:
        print(f"  WARNING: {len(orphaned)} ticket(s) stuck in pending > 4h:")
```

**Implementation plan:**
1. Add a Phase 6 to the watcher skill: "Pipeline Health Check"
   - Count tickets in each `bot-*` label state
   - Detect tickets stuck in `bot-in-progress` for more than
     `STALE_THRESHOLD_HOURS` (default 4h — configurable)
   - Detect tickets stuck in `bot-review-fix` for more than 2 cycles
   - Include health summary in the Slack notification
2. Add stale detection fields to Slack summary:
   ```
   Issue Fix Agent — Watcher Cycle Summary
   ...
   - Stale tickets (>4h in progress): N
   - Orphaned sessions: N
   ```
3. Consider a separate `diagnose` workflow that can be run on-demand
   for detailed pipeline health reporting

**Files to modify:**
- `workflows/jira-watcher/skills/jira-watcher.md` — add Phase 6
- `config/config.env` — STALE_THRESHOLD_HOURS

---

### 2.4 CI-Failing Label

**Status:** TODO
**Priority:** MEDIUM
**Source:** `autofix/src/jira_autofix/labels.py:21`
**Affects:** `issue-review` skill, `review-fix` skill, label state machine

**Problem:** Our `bot-review-fix` label conflates two different scenarios:
1. Human/agent review found code issues (findings to address)
2. CI checks are failing on the PR (tests, linting, build)

These require different fix strategies — code review findings need
targeted file changes, while CI failures need investigation of test output.

**Implementation plan:**
1. Add `bot-ci-failing` label to the state machine:
   ```
   bot-ready-for-review
     → bot-review-fix (review found code issues)
     → bot-ci-failing (CI checks failing)
   ```
2. The review agent checks PR CI status (`gh pr checks`) and uses the
   appropriate label based on whether findings are from code review or CI
3. The review-fix agent handles both labels but adjusts its strategy:
   - `bot-review-fix`: read review comments, fix code issues
   - `bot-ci-failing`: read CI output, fix test/build failures

**Files to modify:**
- `workflows/issue-review/skills/issue-review.md` — Phase 2 (check CI)
- `workflows/review-fix/skills/review-fix.md` — entry gates
- `workflows/jira-watcher/skills/jira-watcher.md` — Phase 3 JQL
- `CLAUDE.md` — label state machine
- `README.md` — label table

---

### 2.5 Two-Agent Parallel Review

**Status:** TODO
**Priority:** MEDIUM
**Source:** `harness/skills/code-review/SKILL.md` (2-agent mode section)
**Affects:** `issue-review` skill

**Problem:** Our review agent runs all 3 lenses (correctness, security,
quality) sequentially in one pass. This means:
- Security review is done by Sonnet (the review model) instead of Opus
- Total review time = sum of all 3 lenses
- No independent perspective — findings from lens 1 bias lens 2

**Solution from harness:**
The code-review skill splits into Security Agent (Opus, isolated) and
Review Agent (Sonnet, functionality + quality), running in parallel:
> "You MUST send BOTH Agent tool calls in a SINGLE message so they run
> concurrently. Do NOT run one agent first and wait."

A coordinator performs setup (load context, read diff, structural sweep),
briefs both agents identically, then merges their results.

**Implementation plan:**
1. Restructure issue-review skill into 3 roles:
   - **Coordinator** (Sonnet): fetches PR, reads diff, loads project
     context, briefs agents, merges results
   - **Security Agent** (Opus, spawned): reviews through security lens only
   - **Review Agent** (Sonnet, spawned): reviews through correctness +
     quality lenses
2. Coordinator passes identical briefing to both agents (diff, change
   intent, project context)
3. Coordinator merges results: dedup, severity consistency, compute scores
4. Update `config/config.env`:
   ```
   REVIEW_SECURITY_MODEL=claude-opus-4-6
   ```

**Trade-off:** Higher cost (Opus for security) but better security coverage
and faster wall-clock time (parallel execution).

**Files to modify:**
- `workflows/issue-review/skills/issue-review.md` — major rewrite
- `config/config.env` — REVIEW_SECURITY_MODEL

---

### 2.6 Prior Review Context Persistence

**Status:** TODO
**Priority:** MEDIUM
**Source:** `harness/skills/code-review/SKILL.md` (prior review check section)
**Affects:** `issue-review` skill, `review-fix` skill

**Problem:** When the review-fix agent pushes changes and the review agent
re-reviews, the review agent starts completely blind. It doesn't know what
it found last time, whether those findings were addressed, or whether fixes
introduced new issues.

**Solution from harness:**
The code-review skill persists findings to a storage path and loads them
on re-review:
> "verify that prior findings were actually fixed — do not just check if
> the code changed. Re-run the same verification that found the original
> bug"

**Implementation plan:**
1. The review agent writes a structured findings summary to the Jira
   comment (it already does this with `## Agent Code Review`)
2. On re-review (cycle 2+), the review agent:
   a. Reads prior `## Agent Code Review` comments from the ticket
   b. For each prior finding, verifies it was actually addressed
   c. Checks if fixes introduced new issues
   d. Reports: "Prior finding X: RESOLVED / STILL PRESENT / REGRESSION"
3. This data already flows through Jira comments (cross-workflow contract),
   so no new persistence mechanism is needed — just smarter re-review logic

**Files to modify:**
- `workflows/issue-review/skills/issue-review.md` — Phase 1 (read priors), Phase 3 (verify fixes)

---

### 2.7 Structured Verdict Schema

**Status:** TODO
**Priority:** LOW
**Source:** `agentic-ci/src/agentic_ci/verdict.py`
**Affects:** `issue-fix` skill (validation.json)

**Problem:** `.audit/validation.json` has no formal schema. Fields are
added ad-hoc across different phases. No validation that required fields
are present or values are within expected ranges.

**Solution from agentic-ci:**
```python
def load_verdict(path, *, required_fields, allowed_verdicts, name="verdict"):
    # Validates: file exists, valid JSON, required fields present,
    # verdict value in allowed set, boolean fields are bool, list fields are list
```

**Implementation plan:**
1. Define the complete schema for `.audit/validation.json`:
   ```json
   {
     "build_passed": true,
     "lint_passed": true,
     "tests_passed": true,
     "tests_total": 42,
     "tests_failed": 0,
     "pre_commit_passed": true,
     "regression_added": true,
     "regression_validates": true,
     "gitleaks_scan": "passed",
     "sensitive_files_check": "passed",
     "diff_additions": 25,
     "diff_deletions": 10,
     "files_touched": 3
   }
   ```
2. Add a final validation step in Phase 9 (before commit) that verifies
   all required fields are present
3. Document the schema in `docs/validation-schema.md`

**New files:**
- `docs/validation-schema.md`

**Files to modify:**
- `workflows/issue-fix/skills/issue-fix.md` — Phase 9 validation check

---

### 2.8 Preflight Environment Checks

**Status:** TODO
**Priority:** MEDIUM
**Source:** `harness/preflight/checks.py`
**Affects:** `issue-fix` skill (new Phase 0), `review-fix` skill

**Problem:** Our entry gates only check if the Jira ticket is accessible
and the label is correct. We don't verify that the session environment
is properly configured (gh auth, git credentials, MCP tools, required
binaries). If `gh` is not authenticated, the agent will fail at Phase 9
(PR creation) after spending 60+ minutes on investigation and fixing.

**Solution from harness:**
15+ environment checks: claude CLI version, gh auth status, repo access,
git credential helper, VPN reachability, secret scanner, MCP server,
Jira credentials, Vertex auth.

**Implementation plan:**
1. Add a "Phase 0: Environment Validation" to the issue-fix skill:
   ```bash
   # Check gh auth
   gh auth status || { echo "ERROR: gh not authenticated"; exit 1; }

   # Check git credential helper
   git config --global credential.helper || echo "WARNING: no credential helper"

   # Check MCP tools available
   # (verify mcp__atlassian__getJiraIssue works with a test call)

   # Check required binaries
   which git gh || { echo "ERROR: required tools missing"; exit 1; }

   # Check gitleaks (optional)
   which gitleaks && echo "gitleaks available" || echo "WARNING: gitleaks not available"
   ```
2. If any critical check fails, exit immediately with `bot-fix-failed`
   and a comment listing what's missing
3. This saves the full session TTL when the environment is misconfigured

**Files to modify:**
- `workflows/issue-fix/skills/issue-fix.md` — add Phase 0
- `workflows/review-fix/skills/review-fix.md` — add Phase 0

---

## Phase 3: Architectural Evolution (Scale and Maturity)

These require larger design changes. Prioritize based on production
experience and observed failure patterns.

---

### 3.1 Orchestrator/Worker Separation

**Status:** FUTURE
**Source:** `autofix-skills/skills/autofix-resolve/SKILL.md`

Split `issue-fix` into a pure orchestrator that dispatches to implement
and review sub-agents. The orchestrator never writes code directly — it
only passes data between agents and makes decisions. This prevents context
exhaustion on complex fixes and enables better state management.

**Key design from autofix-resolve:**
> "Sequencer, not coder. Never write code or modify source files directly.
> All coding happens through the implement agent prompt."

**When to implement:** After observing context exhaustion failures in
production. If the current single-skill approach works for most tickets
(simple 1-3 file fixes), this may not be needed soon.

---

### 3.2 Extension Points (Post-Implement / Post-Review Hooks)

**Status:** FUTURE
**Source:** `autofix-skills/skills/autofix-resolve/SKILL.md`

Allow team-specific skills to inject additional validation at
`post_implement` and `post_review` hooks. Teams could add their own review
agents (like cat-ai-helpers' specialized reviewers) without modifying the
core workflow.

**Design:** A `skill-hooks.json` file in the repo defines extensions:
```json
[
  {"name": "preflight", "args": "--local --fix", "hooks": ["post_implement"]},
  {"name": "security-scan", "args": "", "hooks": ["post_review"]}
]
```

---

### 3.3 LLM Observability (OTEL + Langfuse)

**Status:** FUTURE
**Source:** `agentic-ci/src/agentic_ci/otel.py`, `template-agent/src/core/manager.py`

Full LLM observability: token usage by model, cost per session, API request
counts and durations, active time breakdown. Currently we only capture
session duration in Jira comments.

**Two complementary approaches from sibling projects:**

**Option A — OTEL collector (from agentic-ci):**
Custom OTLP HTTP/JSON receiver that accepts Claude Code's native metrics.
Tracks `claude_code.token.usage`, `claude_code.cost.usage`, and
`claude_code.active_time.total`. Lightweight (runs as subprocess), writes
to JSONL log, provides token rate via sliding window.
Requires an OTEL collector sidecar in the Ambient session container.

**Option B — Langfuse (from template-agent):**
```python
from langfuse.callback import CallbackHandler
langfuse_handler = CallbackHandler(
    trace_name="template-agent",
    environment=settings.LANGFUSE_TRACING_ENVIRONMENT
)
config = RunnableConfig(callbacks=[langfuse_handler])
```
Langfuse is already integrated in the Ambient Platform (per platform
project summary). It provides: token tracking, cost analysis, session
tracing, user feedback collection, and prompt versioning — all via a
hosted dashboard. No custom collector needed.

**Recommendation:** If the Ambient Platform already has Langfuse, use it
(Option B) for session-level tracing. Supplement with OTEL (Option A) only
if Langfuse doesn't capture Claude Code's native OTLP metrics.

**Configuration needed:**
```
LANGFUSE_PUBLIC_KEY=<key>
LANGFUSE_SECRET_KEY=<key>
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=production
```

---

### 3.4 Deep Verification Agent

**Status:** FUTURE
**Source:** `cat-ai-helpers/agents/deep-verification.md`

Add a 5-phase adversarial verification agent (Opus) as an optional 4th
auditor in Phase 4B for high-risk fixes. The agent verifies through 2+
independent approaches: "Nothing is assumed correct until independently
verified through at least two distinct approaches."

Could be triggered by: concurrency signal, security-related fix, public
API change, or all-MEDIUM confidence scores.

---

### 3.5 Structural Sweep for Review

**Status:** FUTURE
**Source:** `harness/skills/code-review/SKILL.md`

Deterministic file categorization before review: Bulk rename, New logic,
Modified logic, Config/manifest, Schema/API, Deleted, Docs/metadata. Each
category has specific completeness checks (e.g., for Deleted: grep the
codebase for stale references).

Ensures exhaustive coverage — "every changed file must be accounted for."

---

### 3.6 Domain-Specific Review Agents

**Status:** FUTURE
**Source:** `cat-ai-helpers/agents/`

Instead of one 3-lens reviewer, dispatch specialized reviewers based on
the target repo's tech stack:
- `security-reviewer` (Opus) — always
- `concurrency-reviewer` (Opus) — if Go/Java and concurrent code modified
- `db-query-reviewer` (Sonnet) — if SQL/ORM changes detected
- `performance-reviewer` (Sonnet) — if hot-path code modified
- `test-reviewer` (Sonnet) — if test files modified

Model selection by domain: Opus for safety-critical (security, concurrency),
Sonnet for cost-sensitive (performance, tests, API contracts).

---

### 3.7 Research/Spike Skill

**Status:** FUTURE
**Source:** `autofix-skills/skills/autofix-research/SKILL.md`

Separate workflow for tickets that need investigation but no code fix.
Writes a research verdict without creating a PR. Useful for:
- Tickets that the triage agent classifies as needing investigation
- Tickets where the root cause is unclear
- Feature requests mistakenly labeled `autofix`

---

### 3.8 CVE Remediation Workflow

**Status:** FUTURE
**Source:** `autofix-skills/skills/autofix-cve-resolve/SKILL.md`

Separate pipeline for CVE-specific fixes: parse CVE details, scan
dependencies, route fix strategy, apply fix, verify, review, generate
VEX statement, create PR, finalize. CVEs have different requirements
(specific version targets, vulnerability verification, VEX documentation)
that don't fit the general bug-fix workflow.

---

### 3.9 Verification Results Table

**Status:** FUTURE
**Source:** `harness/skills/code-review/SKILL.md`

Every review assertion requires executed command output:
```
| Check | Command | Output | Result |
| Stale refs | `grep -r "deleted_fn" .` | `(no output)` | PASS |
```
"PASS without executed command output is not PASS — it is a review defect."

---

### 3.10 Score Trajectory Visualization

**Status:** FUTURE
**Source:** `harness/skills/code-review/SKILL.md`

Track review quality across review-fix cycles with visual progress:
```
Run 1: █████████████████████████████░░░░░░░░░░░  5.7/10
Run 2: ████████████████████████████████████████░  8.8/10
Target: ██████████████████████████████████████████  10/10
```

Low effort but deferred because it requires the prior review context
persistence (2.6) to be implemented first.

---

### 3.11 Post-Merge Feedback Loop

**Status:** FUTURE
**Source:** `template-agent/src/routes/feedback.py`,
`template-agent/src/schema.py`

Collect structured feedback after PRs are merged: did the fix hold? Did
it cause regressions? Was the root cause correct? Feed this back into
future triage and fix confidence calibration.

**Design from template-agent:**
```python
class FeedbackRequest(BaseModel):
    run_id: str       # maps to session/ticket
    key: str          # e.g., "fix-outcome"
    score: float      # 0.0 (regression) to 1.0 (perfect fix)
    kwargs: dict      # {"regression_ticket": "PROJ-999", "comment": "..."}
```
Template-agent records feedback to Langfuse for analytics dashboards.

**Implementation plan for issue-fix-agent:**
1. Add a Phase 5 to the watcher: "Post-Merge Outcome Tracking"
   - For tickets with `bot-merged` label older than 7 days:
     a. Check if any new tickets reference the merged PR (regression signal)
     b. Check if the PR was reverted (`git log --grep="Revert"`)
     c. Check CI status on the target branch post-merge
   - Record outcome as a Jira comment:
     ```
     ## Fix Outcome (7-day check)
     **PR**: [#N](<url>)
     **Status**: Holding / Reverted / Regression detected
     **Details**: <what was found>
     ```
2. Use outcome data to calibrate triage confidence thresholds (Phase 2
   TODO 2.1) — if a signal type (e.g., concurrency) has a high revert rate,
   increase the triage gate strictness.
3. If Langfuse is available (TODO 3.3), record structured scores for
   dashboard analytics.

---

### 3.12 Python Orchestrator with LangGraph

**Status:** FUTURE
**Source:** `template-agent/src/core/agent.py`,
`template-agent/src/core/manager.py`

Build a Python-based orchestrator for the fix pipeline using LangGraph's
`create_react_agent` and `AsyncPostgresSaver` for durable state. This is
the code-based evolution of TODO 3.1 (orchestrator/worker separation).

**Key patterns from template-agent:**

1. **MCP tool integration via library:**
   ```python
   from langchain_mcp_adapters.client import MultiServerMCPClient
   client = MultiServerMCPClient({"atlassian": {
       "url": "http://mcp-atlassian:5001/mcp/",
       "transport": "streamable_http"
   }})
   tools = await client.get_tools()
   ```
   This replaces our current approach of asking the LLM to call MCP tools
   by name — instead, tools are discovered programmatically.

2. **Database-backed conversation checkpointing:**
   ```python
   from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
   async with AsyncPostgresSaver.from_conn_string(db_uri) as checkpoint:
       agent = create_react_agent(model, tools=tools, checkpointer=checkpoint)
   ```
   More robust than file-based state persistence (TODO 2.2) — survives
   container restarts, supports concurrent access.

3. **AgentManager abstraction:**
   Clean separation between API/orchestration layer and agent execution.
   The manager handles input preparation, streaming, state saving, and
   error handling — the agent just processes messages.

**When to implement:** Only if the markdown-skill approach hits fundamental
limits (state management failures, context exhaustion on most tickets,
need for programmatic tool control). The current skill-based approach is
simpler and sufficient for the initial deployment.

**Prerequisites:**
- Python runtime in the Ambient session container
- PostgreSQL access (or use Ambient's existing database)
- `langchain-mcp-adapters`, `langgraph`, `langfuse` packages

---

### 3.13 OpenShift Deployment Manifests

**Status:** FUTURE
**Source:** `template-agent/deployment/openshift/`

If the watcher ever needs to run as a persistent service (instead of
Ambient cron sessions), template-agent provides a complete kustomize
deployment reference:

- `deployment.yaml` — Pod spec with liveness/readiness probes, resource
  limits (256Mi-512Mi memory, 100m-500m CPU), environment from ConfigMap +
  Secret
- `configmap.yaml` — Non-sensitive config (log level, MCP URL, transport)
- `secret.yaml` — Sensitive config (DB credentials, Langfuse keys, Google
  creds)
- `service.yaml` + `route.yaml` — Service exposure
- `kustomization.yaml` — Overlay management

**Key pattern:** Secrets and config are cleanly separated. All credentials
come from SecretRef, all behavioral config from ConfigMapRef. Health
probes use `/health` endpoint with appropriate timeouts.

---

## Cross-Reference: Source Projects

| Project | Items Sourced | Key Patterns |
|---------|--------------|--------------|
| `agentic-ci` | 1.1, 1.6, 1.7, 1.8, 1.9, 2.7, 3.3 | Gates system, git security, OTEL, verdict schema |
| `autofix` | 1.2, 1.3, 1.4, 1.5, 1.10, 2.3, 2.4 | Label state machine, pre/post gates, diagnostics |
| `autofix-skills` | 2.1, 2.2, 3.1, 3.2, 3.7, 3.8 | State persistence, triage rubric, orchestrator pattern |
| `cat-ai-helpers` | 3.4, 3.6 | Deep verification, specialized review agents |
| `harness` | 2.5, 2.6, 2.8, 3.5, 3.9, 3.10 | Code review methodology, preflight, structural sweep |
| `template-agent` | 3.3, 3.11, 3.12, 3.13 | Langfuse tracing, feedback loop, LangGraph orchestrator, OpenShift deployment |
| `rtk` | (already integrated) | Token optimization — in Phase 1 |
| `workflows` | (ambient.json patterns) | Controller-driven flow — deferred |

---

## Summary — Implementation Sprints

| Sprint | Bucket | Items | Effort | Gate |
|--------|--------|-------|--------|------|
| **Sprint 1** | MVP NEEDED | 1.6, 1.8, 1.9, 1.10, 2.8 | ~1 hour | Before first watcher run |
| **Sprint 2** | MVP GOOD-TO-HAVE | 1.1, 1.3, 1.5, 2.2, 2.3, 2.7 | ~2 hours | Before stakeholder demo |
| **Sprint 3** | PRODUCTION NEEDED | 1.2, 1.4, 1.7, 2.1, 2.4, 2.6, 3.3, 3.13 | ~1-2 days | Before real team tickets |
| **Sprint 4+** | PROD GOOD-TO-HAVE | 2.5, 3.1-3.12 | Ongoing | Based on production pain |

**Total: 31 items** (5 MVP needed + 6 MVP nice + 8 prod needed + 12 prod nice)
