# Platform Pivot Analysis — Enterprise Harness Framework

> Date: 2026-06-17
> Context: Company direction shifting from Ambient Platform to OpenCode +
> OpenShell. This document explores possible target architectures and a
> longer-term enterprise direction for issue-fix-agent.

---

## Three Reference Architectures

### 1. Current: issue-fix-agent on Ambient Platform

```
Jira (autofix label)
  → Watcher (Ambient session, Sonnet, 15m)
    → Fix Agent (Ambient session, Opus, 150m)
      → Review Agent (Ambient session, Sonnet, 30m)
        → Review-Fix Agent (Ambient session, Opus, 45m)
          → Human merge
```

**Strengths:**
- Label-based state machine (no database needed)
- Cross-workflow contracts via Jira comments
- Security hardening (URL validation, sensitive file blocklist, git hardening)
- 3-sub-agent audit loop with convergence checking
- Signal-driven investigation strategies

**Weaknesses:**
- Tightly coupled to Ambient (session dispatch, MCP hosting, ambient.json)
- Markdown skill files = instructions, not code (no error handling, state, types)
- No input/output guardrails beyond prompt injection defense
- No observability beyond Jira comment telemetry
- No memory system (knowledge doesn't accumulate across tickets)

### 2. OLS Agentic Sandbox (OpenShift Lightspeed)

```
Proposal CR
  → Operator watches CRDs
    → Creates SandboxTemplate → Sandbox Pod
      → Agent runs inside sandbox (/v1/agent/run)
        → ApprovalPolicy gates (Analysis → Execution → Verification)
```

**Key CRDs:** Proposal, Agent, LLMProvider, ApprovalPolicy, SandboxTemplate,
SandboxClaim, Sandbox

**Strengths:**
- Kubernetes-native (CRDs, operators, RBAC)
- Built-in approval stages (Automatic/Manual per stage)
- Multi-model support (OpenAI, Anthropic via LLMProvider CR)
- Sandbox isolation (per-agent pod with defined resources)
- OpenShift integration (cluster access, service accounts)

**Weaknesses:**
- Early/alpha — 6 known issues as of 2026-06-04
- No Jira integration built-in
- No MCP server support documented
- No multi-agent orchestration (single agent per Proposal)
- No memory or knowledge accumulation
- OpenAI-focused (Anthropic provider not fully working)

### 3. Agent Harness Engineering Framework

```
User Input
  → Input Guard (PII, injection, policy)
    → Retrieve Context (ChromaDB long-term memory)
      → Agent (LangGraph, LLM reasoning)
        → Tool Orchestration (approval gates for high-stakes)
          → Output Guard (safety, content validation)
            → Verification Loop (self-critique, confidence gating)
              → Observability (LangFuse tracing)
```

Source: https://nileshprajapati.net/blog/2026/agent-harness-engineering/
Repo: https://github.com/prajapatin/agent-harness-engineering

**Strengths:**
- Production-focused guardrails (input + output, bidirectional)
- Self-critique verification with confidence scoring
- Dual-tier memory (SQLite short-term + ChromaDB long-term)
- LangFuse observability (tracing, prompt versioning, LLM-as-judge evals)
- Provider-agnostic (LiteLLM: OpenAI, Anthropic, Groq, Ollama)
- Human-in-the-loop approval gates per tool
- Reusable framework (not tied to one domain)

**Weaknesses:**
- No Kubernetes/sandbox integration
- No multi-agent orchestration
- Single-agent, single-session model
- Demo-quality (smart factory example), not battle-tested
- No git/code-change workflow

---

## Gap Analysis: What issue-fix-agent Has vs What the Harness Needs

| Capability | issue-fix-agent | Harness Framework | OLS Sandbox | Need |
|-----------|----------------|-------------------|-------------|------|
| **Input guardrails** | Prompt injection defense (skill-level) | Pydantic policies (PII, injection, custom) | None | Harness is stronger |
| **Output guardrails** | Self-review diff, sensitive file blocklist | Safety policies, content filtering | None | Harness is stronger |
| **Verification** | 3-sub-agent audit loop | Self-critique + confidence gating | None | Both useful, different levels |
| **Approval gates** | Human PR merge only | Per-tool approval | Per-stage (Analysis/Exec/Verify) | OLS model is best fit |
| **Memory** | None | Dual-tier (SQLite + ChromaDB) | None | Need to add |
| **Observability** | Jira comment telemetry only | LangFuse (tracing, evals, cost) | None | Harness is much stronger |
| **Multi-agent** | 4 workflows (watcher, fix, review, review-fix) | Single agent | Single agent | issue-fix-agent is ahead |
| **State machine** | Label-based (Jira labels) | LangGraph checkpointer | CRD-based (Proposal status) | All different approaches |
| **Sandbox** | Container pod (Ambient) | None | K8s pod (SandboxTemplate) | OLS/OpenShell needed |
| **Tool orchestration** | MCP tools + bash | HarnessTool + registry | Sandbox tools | All different |
| **Provider agnostic** | Claude only (Opus/Sonnet) | LiteLLM (100+ models) | OpenAI/Anthropic via LLMProvider | Harness is strongest |
| **Git workflow** | Full (clone, branch, fix, PR, review) | None | None | issue-fix-agent is unique |
| **Jira integration** | Full (labels, comments, transitions) | None | None | issue-fix-agent is unique |
| **Retry/recovery** | bot-retry label, max 2 retries | Verification retry (max 3) | maxAttempts in ApprovalPolicy | All have retry |
| **Security** | URL validation, git hardening, blocklist | PII redaction, policy engine | Pod isolation, RBAC | Need all three |

---

## Proposed Direction: Enterprise Harness for Issue Fixing

One possible long-term direction is to combine selected strengths of
all three (this is a strategic design option, not yet a committed plan):

### Layer Architecture

```
L1 — Infrastructure:   OpenShift / Kubernetes
L2 — Sandbox:          OpenShell (or OLS SandboxTemplate)
L3 — Harness:          Enterprise Agent Harness (LangGraph-based)
  ├── Input Guards     (from harness framework)
  ├── Output Guards    (from harness framework)
  ├── Memory           (from harness framework: ChromaDB + SQLite)
  ├── Observability    (from harness framework: LangFuse)
  ├── Verification     (from issue-fix-agent: 3-sub-agent audit)
  ├── Approval Gates   (from OLS: CRD-based stage approvals)
  └── Tool Registry    (from harness framework: HarnessTool + MCP)
L4 — Agent Runtime:    OpenCode (or Claude Code)
L5 — Model:            Claude Opus/Sonnet, GPT-5.x, Gemini (via LiteLLM)
```

### What to Preserve from issue-fix-agent

1. **Skill logic** — investigation strategies, signal classification, audit
   loop, complexity gate, fix plan structure. These are domain knowledge
   that translates to any runtime.

2. **Label state machine** — Jira labels as workflow state. This is
   tracker-agnostic (could work with GitHub Issues, Linear, etc.)

3. **Cross-workflow contracts** — structured comment formats for
   inter-agent communication. The format is the protocol, not the platform.

4. **Security hardening** — git hook disabling, URL validation, sensitive
   file blocklist, branch/commit sanitization. These are universal.

5. **Review methodology** — 3-lens review (correctness, security, quality)
   with evidence gates and validation chain.

### What to Add from Harness Framework

1. **Input/Output Guards** — Pydantic-based policy engine for PII
   detection, prompt injection, content validation. Apply to Jira ticket
   content (input) and agent-generated code/comments (output).

2. **Dual-tier Memory** — short-term (conversation checkpoints) + long-term
   (semantic knowledge across tickets). Enables: "this repo had a similar
   bug last month, here's what worked."

3. **LangFuse Observability** — tracing every LLM call, cost tracking per
   ticket, prompt versioning, LLM-as-judge evaluations. Replaces our
   ad-hoc Jira comment telemetry.

4. **Self-Critique Verification** — confidence scoring on agent outputs
   (not just audit loop on plans). Apply to: fix implementation, review
   findings, root cause analysis.

5. **Provider Agnosticism** — LiteLLM abstraction. Run fix agent on
   Claude Opus, review on GPT-5, audit on Gemini — whatever is best/cheapest.

### What to Add from OLS Sandbox

1. **CRD-based Orchestration** — Proposal CR as the entry point instead of
   Jira label polling. An operator watches Proposals and creates sandboxed
   agent pods.

2. **Approval Stages** — ApprovalPolicy CR defining which stages need human
   approval. Maps to: Analysis=Automatic, Execution=Manual, Verification=
   Automatic (or configurable per project).

3. **Sandbox Isolation** — SandboxTemplate defines the pod spec, resource
   limits, network policies. Each agent runs in its own sandbox.

4. **RBAC** — Kubernetes RBAC for agent service accounts. Agents get only
   the permissions they need (cluster-reader, not cluster-admin).

### What to Build New

1. **Multi-Agent Orchestrator** — neither the harness framework nor OLS
   sandbox support multi-agent workflows. Need an orchestrator (like our
   watcher) that: creates Proposals/sandbox instances for each stage,
   passes context between stages, manages the label state machine.

2. **Jira Integration as a Tool** — wrap Jira REST API operations as
   HarnessTool instances (search, get, edit labels, add comments,
   transition). Register in ToolRegistry. Could use mcp-atlassian or
   direct REST.

3. **Git Workflow as Tools** — wrap git operations (clone, branch, commit,
   push) and GitHub operations (PR create, review) as HarnessTools with
   approval gates.

4. **Knowledge Accumulation** — after each fix, store: root cause patterns,
   fix approaches, failure modes in ChromaDB. Future tickets benefit from
   accumulated knowledge.

---

## Migration Path

### Phase 1: Extract portable components (no platform dependency)
- Extract skill logic into Python modules (investigation strategies,
  signal classification, audit loop)
- Extract security hardening into reusable functions
- Extract Jira operations into HarnessTool implementations
- Extract git/GitHub operations into HarnessTool implementations

### Phase 2: Build harness core (LangGraph + LangFuse)
- Implement HarnessAgent with input/output guards
- Add dual-tier memory (SQLite + ChromaDB)
- Add LangFuse observability
- Add self-critique verification loop

### Phase 3: Build orchestrator (multi-agent)
- Implement watcher/orchestrator as a LangGraph graph
- Implement fix, review, review-fix as separate agent configs
- Wire label state machine through the orchestrator
- Add approval gates per stage

### Phase 4: Add sandbox layer (OpenShell or OLS)
- Define SandboxTemplates for each agent role
- Integrate with OpenShell policy engine or OLS operator
- Add RBAC per agent service account
- Test sandbox isolation

### Phase 5: Production hardening
- Provider switching (LiteLLM for multi-model)
- Cost tracking and budget caps (LangFuse)
- Knowledge accumulation (ChromaDB)
- Scale testing (concurrent tickets)

---

## Decision Points

1. **Sandbox: OpenShell vs OLS SandboxTemplate?**
   OpenShell is upstream (NVIDIA), OLS is internal (Red Hat). If the company
   direction is OpenShell, use that. If OLS agentic-operator is the
   internal standard, use that. They solve the same L2 problem differently.

2. **Agent runtime: OpenCode vs Claude Code?**
   OpenCode is open-source and multi-model. Claude Code is Claude-only but
   more mature. LiteLLM abstraction makes the runtime choice less critical.

3. **Orchestrator: LangGraph vs custom operator?**
   LangGraph is Python-native with built-in state management. A K8s
   operator (like OLS agentic-operator) is more cloud-native but requires
   Go. LangGraph is faster to build; operator is more enterprise.

4. **Jira integration: MCP vs direct REST?**
   MCP is the standard but adds a dependency (mcp-atlassian server). Direct
   REST is simpler and more portable. Could support both via the
   ToolRegistry pattern.
