# Migration Pros/Cons — Ambient vs Enterprise Harness

> Date: 2026-06-17
> Investment to date: 18 commits, 2,636 lines across 12 workflow markdown
> files, 6,156 lines of docs, 4 workflows, built over ~4 days with
> multiple audit rounds.

---

## Option A: Stay on Ambient (Current Codebase)

### Pros

| # | Pro | Details |
|---|-----|---------|
| 1 | **Already built** | 4 workflows, 12 workflow markdown files, 8-phase watcher, 13-phase fix agent (Phases 0-10 including 4A/4B), 3-lens review — all written and documented |
| 2 | **Ready to test** | Config set for OBSINTA staging, setup guide with 21 test scenarios, production checklist |
| 3 | **Battle-tested design** | Multiple audit rounds (Architecture, PE, Agent Expert) caught and fixed numerous issues across design and implementation |
| 4 | **Zero code to write** | Entirely markdown-based — no Python, no build, no dependencies beyond Ambient |
| 5 | **Jira integration done** | Label state machine, cross-workflow contracts, auto-recovery, retry, cancellation — all implemented |
| 6 | **Security hardening done** | URL validation, git hardening, sensitive file blocklist, branch/commit sanitization |
| 7 | **Low operational overhead** | Watcher runs as a cron session, no infrastructure to maintain beyond Ambient |
| 8 | **Fast iteration** | Changing agent behavior = editing a markdown file, no redeploy |

### Cons

| # | Con | Impact |
|---|-----|--------|
| 1 | **Platform is being deprioritized** | Company direction away from Ambient — may lose platform support, updates, bug fixes |
| 2 | **Vendor lock-in** | Tied to Ambient session management, MCP hosting, ambient.json format — no portability |
| 3 | **Claude-only** | Hardcoded to Opus/Sonnet — can't use GPT-5, Gemini, or local models |
| 4 | **No input/output guardrails** | Only prompt-level injection defense — no PII detection, no content filtering, no policy engine |
| 5 | **No observability** | Jira comment telemetry only — no token tracking, no cost dashboards, no tracing |
| 6 | **No memory** | Agent starts fresh every ticket — no knowledge accumulation across fixes |
| 7 | **Markdown = fragile** | 1,020-line skill file is instructions, not code — no types, no tests, no error handling |
| 8 | **MCP dependency unresolved** | Jira MCP availability in Ambient remains uncertain; the design already requires REST fallback for some label operations |
| 9 | **No sandbox isolation** | Agent runs in standard container — no kernel-level security (Landlock, network policies) |
| 10 | **Single-threaded watcher** | Polling every 20 min — no event-driven dispatch, 40-60 min latency per pipeline stage |

### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Ambient deprecated | HIGH (company direction) | HIGH (entire system breaks) | Migration |
| MCP never works | MEDIUM (platform issue) | HIGH (Jira integration blocked) | curl fallback exists |
| Skill file too long for LLM | LOW (tested at 1,020 lines) | MEDIUM (instruction degradation) | Split into smaller files |
| Security incident (no sandbox) | LOW (staging only) | HIGH (credential exposure) | Git hardening mitigates |

---

## Option B: Migrate to Enterprise Harness (5-Phase Plan)

### Phase 1: Extract Portable Components

**What:** Convert markdown skill logic to Python modules. Extract Jira
operations, git operations, security hardening into reusable functions.

| Pro | Con |
|-----|-----|
| Preserves all domain knowledge (investigation strategies, audit loop, review methodology) | Rewrite effort — 2,636 lines of markdown → Python |
| Testable code (unit tests, type hints, error handling) | Markdown was easier to iterate with an LLM |
| Reusable across any agent runtime | Need Python expertise vs. just writing instructions |
| Can run in parallel with Option A (no breaking change) | Dual maintenance during transition |

**Effort:** 1-2 weeks
**Risk:** Low (additive, doesn't break existing system)

### Phase 2: Build Harness Core (LangGraph + LangFuse)

**What:** Implement HarnessAgent with input/output guards, dual-tier
memory, LangFuse observability.

| Pro | Con |
|-----|-----|
| Input guardrails catch PII, injection before LLM sees them | New dependency: LangGraph, LangFuse, ChromaDB, LiteLLM |
| Output guardrails catch hallucinated code, unsafe changes | More infrastructure to run (LangFuse server, ChromaDB) |
| LangFuse gives real cost tracking, tracing, prompt versioning | Learning curve for the full LangGraph state machine model |
| Self-critique adds quality layer beyond audit loop | Over-engineering risk for a system that might only fix 5 tickets/day |
| Memory accumulates knowledge across tickets | ChromaDB needs hosting and maintenance |
| Provider-agnostic (switch models without code change) | LiteLLM adds abstraction overhead |

**Effort:** 2-3 weeks
**Risk:** Medium (new tech stack, integration complexity)

### Phase 3: Build Multi-Agent Orchestrator

**What:** Implement watcher/orchestrator as LangGraph graph. Wire fix,
review, review-fix as separate agent configs. Label state machine
through orchestrator.

| Pro | Con |
|-----|-----|
| Event-driven (webhook) instead of 20-min polling | Orchestrator is the most complex component to build |
| Proper state management (LangGraph checkpointer) | Jira label state machine needs reimplementation |
| Can run agents in parallel (not sequential sessions) | Testing multi-agent flows is hard |
| Retry/recovery is code-level (not label-based) | Loses the simplicity of "just add a Jira label" |

**Effort:** 2-3 weeks
**Risk:** High (most complex phase, most things can break)

### Phase 4: Add Sandbox Layer

**What:** Integrate OpenShell or OLS SandboxTemplate for agent isolation.

| Pro | Con |
|-----|-----|
| Kernel-level security (Landlock, network policies) | OpenShell is early preview — stability risk |
| Each agent in its own sandbox | Adds operational complexity (sandbox lifecycle management) |
| Policy-driven resource limits | Slower agent startup (sandbox creation overhead) |
| Matches company direction (OpenShell) | May conflict with OLS agentic-operator approach |

**Effort:** 1-2 weeks
**Risk:** High (early-stage technology, integration unknowns)

### Phase 5: Production Hardening

**What:** Multi-model support, cost caps, knowledge accumulation,
scale testing.

| Pro | Con |
|-----|-----|
| Use cheapest model per task (GPT-5-mini for triage, Opus for fix) | Multi-model testing matrix is exponential |
| Cost caps prevent runaway spend | Need token-level cost tracking (LangFuse provides this) |
| Knowledge base improves fix quality over time | Knowledge curation needed to prevent garbage accumulation |
| Scale to 50+ tickets/day | Needs load testing infrastructure |

**Effort:** 2-3 weeks
**Risk:** Medium

---

## Side-by-Side Comparison

| Dimension | Option A (Ambient) | Option B (Enterprise Harness) |
|-----------|-------------------|-------------------------------|
| **Time to first test** | Potentially soon, but with Ambient platform risk and Jira MCP uncertainty | 4-6 weeks (Phases 1-3 minimum) |
| **Total effort** | Done (4 days invested) | 8-13 weeks additional |
| **Platform risk** | HIGH (Ambient deprioritized) | LOW (open-source stack) |
| **Vendor lock-in** | HIGH (Ambient + Claude) | LOW (LiteLLM + OpenShell) |
| **Security** | Application-level only | Application + kernel-level |
| **Observability** | Jira comments | LangFuse (full tracing, cost, evals) |
| **Memory** | None | Dual-tier (short + long term) |
| **Guardrails** | Prompt-level | Pydantic policy engine |
| **Testability** | Manual (run agent, check Jira) | Unit tests, integration tests |
| **Multi-model** | No (Claude only) | Yes (LiteLLM, 100+ models) |
| **Maintenance** | Edit markdown files | Python codebase, dependencies, infra |
| **Team adoption** | Low barrier (just labels + Jira) | Higher barrier (code, deploy, monitor) |
| **Scalability** | 20-min polling, 8 concurrent (4 fix + 2 review + 2 review-fix) | Event-driven, configurable |

---

## Hybrid Option: Option C

**Don't choose — do both strategically.**

1. **Keep current Ambient system for immediate testing** (if Jira MCP gets
   unblocked via curl fallback). Prove the concept works end-to-end on
   real tickets. Collect data on fix quality, failure rates, costs.

2. **Start Phase 1 in parallel** — extract portable components into Python.
   This is additive and low-risk. The Python modules can be tested
   independently.

3. **Use production data to guide Phase 2-3 design** — actual ticket data
   tells you which guardrails matter, what memory is useful, where
   observability gaps hurt.

4. **Phase 4-5 when OpenShell/OLS stabilizes** — don't build on early
   preview technology. Wait for GA or at least beta.

### Pros of Hybrid
- Get real-world data NOW (not in 8-13 weeks)
- Domain knowledge validated before migration
- No wasted work — everything portable transfers
- Platform risk managed (working system + migration path)

### Cons of Hybrid
- Dual maintenance during transition
- Team splits attention between two systems
- Ambient investment may feel "wasted" (it's not — it's validated design)

---

## Recommendation

**Option C (Hybrid)** is the strongest path because:

1. The Ambient system's value is in the **domain design** (audit loop,
   review methodology, label state machine, security hardening), not the
   platform binding. This design was validated through 30+ audit findings
   across 4 independent reviewers.

2. Migrating without production data means guessing which harness features
   matter. Running even 10 tickets through the Ambient system gives data
   on: failure rates, common root causes, audit loop effectiveness, token
   costs, review quality.

3. Phase 1 (extract portable components) has **zero risk** and makes the
   eventual migration faster regardless of target platform.

4. OpenShell is "early preview" — building on it now risks rework when the
   API changes. Phase 4 should wait for stability.

---

## Related Documents

This doc is the **decision document**. Two companion docs provide detail:

- `docs/plan-opencode-openshell-migration.md` — **near-term tactical plan**:
  translate skill files to OpenCode format, build external watcher script,
  add OpenShell sandboxing. ~5-8 weeks. Keeps markdown skills, changes
  only the runtime layer.

- `docs/analysis-platform-pivot.md` — **long-term strategic exploration**:
  enterprise harness with LangGraph, LangFuse, ChromaDB, LiteLLM.
  12-20 weeks. Rewrites skills to Python, adds guardrails + memory +
  observability. This is an option under evaluation, not a committed plan.

The recommended sequence: do the tactical migration (doc 2) first, collect
production data, then evaluate the enterprise harness (doc 3) based on
observed gaps.
