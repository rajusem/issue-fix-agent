# Plan: <TICKET-KEY> — <Title>

> **Ticket**: [<TICKET-KEY>](https://<JIRA_SITE>/browse/<TICKET-KEY>)
> **Target Repo**: <https://github.com/org/repo>
> **Created**: <date>
> **Status**: Draft | Auditing | Approved | Implemented

---

## Jira Integration

- **Plan → Jira**: this doc references the ticket key and PR URL
- **Jira → Plan**: Jira comments (`## Fix Plan`, `## Fix Applied`,
  `## Fix Failed`) contain summaries; this plan doc contains the full
  audit trail with per-round findings and false positive tracking

---

## Context

Why this change is needed. What problem it solves. What triggered it.

## Plan

### Approach

What will be changed and why.

### Files to Modify

| File | Change |
|------|--------|
| `path/to/file` | What changes |

### Dependencies

Any blockers, prerequisites, or related tickets.

---

## Audit Trail

### Round 1

**Date**: <date>
**Reviewers**: Architecture, PE, SDLC Expert, Agent Expert (4 independent reviewers)

| Reviewer | Verdict | Findings | Real Issues | False Positives |
|----------|---------|----------|-------------|-----------------|
| Architecture | approve/revise | N | N | N |
| PE | approve/revise | N | N | N |
| SDLC Expert | approve/revise | N | N | N |
| Agent Expert | approve/revise | N | N | N |

**Combined real findings:**

| ID | Severity | Reviewer | Description | Resolution |
|----|----------|----------|-------------|------------|
| R1-001 | CRITICAL/MAJOR/MINOR | which | what | how it was fixed |

**False positives rejected:**

| ID | Reviewer | Claimed Issue | Why False Positive |
|----|----------|--------------|-------------------|
| R1-FP1 | which | what they said | evidence it's not real |

**Plan revisions from Round 1:**
- What changed in the plan based on findings

---

### Round 2

(Same structure as Round 1)

---

### Round N (if needed)

(Repeat until all 4 reviewers approve)

---

## Implementation

**Date**: <date>
**PR**: [#N](<pr_url>)
**Files changed**: N files, +X/-Y lines

### Post-Implementation Audit

| Reviewer | Verdict | Issues Found |
|----------|---------|-------------|
| Architecture | approve | 0 |
| PE | approve | 0 |
| SDLC Expert | approve | 1 MINOR |
| Agent Expert | approve | 0 |

**Final minor fixes**: (if any)

---

## Outcome

What was delivered. Any follow-up items identified.

**History**: `git log -- docs/plans/<PROJECT>/<TICKET-KEY>.md`
