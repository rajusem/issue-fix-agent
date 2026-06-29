# Issue-Fix Agent — Model Evaluation

> **Environment:** Local macOS (not OpenShift/OpenShell). Agents ran via
> `opencode run` with `--dangerously-skip-permissions` and `script -q` PTY
> wrapper. No sandbox isolation, no TTL enforcement, no resource limits.
> Production deployment on OpenShift with OpenShell sandbox is a separate
> validation step.

## Test Matrix

**6 issues × 7 models = 42 test runs (~40 completed)**

### Issues

| # | Original Issue | Repo (Fork) | Branch | Language | Difficulty | Human Fix PR | Files | +/- |
|---|---------------|-------------|--------|----------|-----------|-------------|-------|-----|
| 1 | OBSINTA-1176 | [rajusem/obs-mcp](https://github.com/rajusem/obs-mcp) | `issue-fix-OBSINTA-1176` | Go | Small | [rhobs/obs-mcp#38](https://github.com/rhobs/obs-mcp/pull/38) | 2 | +10/-3 |
| 2 | ACM-35375 | [rajusem/agent-swarm](https://github.com/rajusem/agent-swarm) | `issue-fix-ACM-35375` | Python | Hard | [jnpacker/agent-swarm#36](https://github.com/jnpacker/agent-swarm/pull/36) | 6 | +259/-27 |
| 3 | OCPBUGS-45921 | [rajusem/release](https://github.com/rajusem/release) | `issue-fix-OCPBUGS-45921` | YAML | Easy (huge repo) | [openshift/release#75813](https://github.com/openshift/release/pull/75813) | 4 | +4/-0 |
| 4 | LEADS-205 | [rajusem/lightspeed-evaluation](https://github.com/rajusem/lightspeed-evaluation) | `issue-fix-LEADS-205` | Python | Medium (refactor) | [lightspeed-core/lightspeed-evaluation#141](https://github.com/lightspeed-core/lightspeed-evaluation/pull/141) | 4 | +26/-122 |
| 5 | LEADS-230 | [rajusem/lightspeed-evaluation](https://github.com/rajusem/lightspeed-evaluation) | `issue-fix-LEADS-230` | Python | Small | [lightspeed-core/lightspeed-evaluation#163](https://github.com/lightspeed-core/lightspeed-evaluation/pull/163) | 5 | +13/-14 |
| 6 | OBSINTA-1329 | [rajusem/multicluster-observability-operator](https://github.com/rajusem/multicluster-observability-operator) | `issue-fix-OBSINTA-1329` | Go | Small | [stolostron/multicluster-observability-operator#2447](https://github.com/stolostron/multicluster-observability-operator/pull/2447) | 2 | +27/-3 |

### Models

| # | Model | Provider | OpenCode Model ID | Prior Result |
|---|-------|----------|-------------------|-------------|
| 1 | Qwen 3.6 35B-A3B | LiteMaaS (cluster) | `litemaas/Qwen3.6-35B-A3B` | PASS |
| 2 | Qwen3-Coder 30B | Ollama (local) | `ollama/qwen3-coder-fixed` | FAIL (hallucinated) |
| 3 | Claude Opus 4.6 | Vertex AI | `google-vertex-anthropic/claude-opus-4-6` | PASS |
| 4 | Claude Sonnet 4.6 | Vertex AI | `google-vertex-anthropic/claude-sonnet-4-6` | PASS |
| 5 | Gemma4 31B | Ollama (local) | `ollama/gemma4:31b` | FAIL |
| 6 | MiniMax M2.5 | Ollama Cloud | `ollama/minimax-m2.5:cloud` | PASS |
| 7 | deepseek-r1:32b | Ollama (local) | `ollama/deepseek-r1:32b` | Never tested |

### Issue Descriptions (for Jira tickets)

#### OBSINTA-1176 — Alertmanager transport config ignored
`NewAlertmanagerClient` was creating a default HTTP client via `client.NewHTTPClientWithConfig`, completely ignoring the `RoundTripper` from `apiConfig`. This discarded TLS settings (`--insecure`) and bearer token authentication, causing x509 and 401 errors when connecting to secured Alertmanager endpoints.

**Expected fix**: Use `go-openapi/runtime/client.NewWithClient` to pass through the configured transport, matching how the Prometheus client already works.

#### ACM-35375 — Session creation crashes (NOT NULL constraint + MissingGreenlet)
Three bugs introduced when K8s cleanup (ACM-34863) removed fields from the `Session` model without DB migrations:
1. `NOT NULL constraint failed: sessions.persist` — removed columns still in DB schema
2. `MissingGreenlet` crash on duplicate session name — `await db.refresh(ws)` missing after rollback
3. Missing template context in `IntegrityError` handler — `mcp_servers` and `prompt_sources` not passed

**Expected fix**: Add DROP COLUMN migrations, refresh after rollback, fix template context, remove stale Mode card.

#### OCPBUGS-45921 — HyperShift serial conformance test ingress failure
e2e-aws-ovn-conformance-serial creates a HyperShift hosted cluster with 3 worker nodes but SingleReplica infrastructure topology (default). Ingress controller runs with only 1 replica, vulnerable to NoExecute taint eviction from serial conformance tests.

**Expected fix**: Add `HYPERSHIFT_INFRA_TOPOLOGY=HighlyAvailable` to 4 periodics YAML configs (4.19, 4.20, 4.21, 4.22).

#### LEADS-205 — Duplicate data validation in pipeline
Data is validated during load AND again in the evaluation pipeline. The duplicate validation is unnecessary overhead.

**Expected fix**: Remove duplicate validation from pipeline, make validation methods internal-only. Deletion-heavy refactor (+26/-122).

#### LEADS-230 — Missing metric_metadata value in CSV
The `metric_metadata` column in CSV output is empty because of an incorrect property name. The field isn't populated despite containing all properties for a metric used for evaluation.

**Expected fix**: Fix property name reference in data model and evaluator. Update CSV column ordering. Small bug fix across 5 files.

#### OBSINTA-1329 — Right-sizing policies deployed to non-OpenShift clusters
rs-prom-rules-policy and rs-virt-prom-rules-policy are deployed to non-OpenShift clusters (e.g. AKS) that lack the openshift-monitoring namespace and Prometheus CRDs.

**Expected fix**: Add `vendor=OpenShift` label selector to Placement defaults in `placement.go` + update test.

---

## Run Command Template

```bash
# Source credentials
set -a && source .env && set +a

# Investigation phase (with PTY wrapper for non-interactive mode)
script -q /tmp/eval-investigate-<TICKET>.log \
  /Users/rzalavad/.opencode/bin/opencode run \
  --dangerously-skip-permissions \
  --agent fix-investigate \
  -m <MODEL_ID> \
  "Investigate Jira ticket <TICKET-KEY>. Follow the skill."

# Swap label: bot-plan-ready → bot-in-progress (manual step for eval)

# Implementation phase (after investigation completes)
script -q /tmp/eval-implement-<TICKET>.log \
  /Users/rzalavad/.opencode/bin/opencode run \
  --dangerously-skip-permissions \
  --agent fix-implement \
  -m <MODEL_ID> \
  "Implement the approved fix for <TICKET-KEY>. Follow the skill."
```

**Notes:**
- `--dangerously-skip-permissions` is eval-only — bypasses all permission prompts for unattended runs
- `script -q` provides PTY wrapper needed for OpenCode's non-interactive mode
- Clean up `target-repo/` between runs: `rm -rf target-repo/`

---

## Results

### Jira Ticket Map (Stage: stage-redhat.atlassian.net)

Parent Story: [OBSINTA-1325](https://stage-redhat.atlassian.net/browse/OBSINTA-1325)

| Issue | Qwen 3.6 35B | Qwen3-Coder 30B | Opus 4.6 | Sonnet 4.6 | Gemma4 31B | MiniMax M2.5 | DeepSeek R1 32B |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| OBSINTA-1176 | [1327](https://stage-redhat.atlassian.net/browse/OBSINTA-1327) | [1328](https://stage-redhat.atlassian.net/browse/OBSINTA-1328) | [1329](https://stage-redhat.atlassian.net/browse/OBSINTA-1329) | [1330](https://stage-redhat.atlassian.net/browse/OBSINTA-1330) | [1331](https://stage-redhat.atlassian.net/browse/OBSINTA-1331) | [1332](https://stage-redhat.atlassian.net/browse/OBSINTA-1332) | [1333](https://stage-redhat.atlassian.net/browse/OBSINTA-1333) |
| ACM-35375 | [1334](https://stage-redhat.atlassian.net/browse/OBSINTA-1334) | [1335](https://stage-redhat.atlassian.net/browse/OBSINTA-1335) | [1336](https://stage-redhat.atlassian.net/browse/OBSINTA-1336) | [1337](https://stage-redhat.atlassian.net/browse/OBSINTA-1337) | [1338](https://stage-redhat.atlassian.net/browse/OBSINTA-1338) | [1339](https://stage-redhat.atlassian.net/browse/OBSINTA-1339) | [1340](https://stage-redhat.atlassian.net/browse/OBSINTA-1340) |
| OCPBUGS-45921 | [1341](https://stage-redhat.atlassian.net/browse/OBSINTA-1341) | [1342](https://stage-redhat.atlassian.net/browse/OBSINTA-1342) | [1343](https://stage-redhat.atlassian.net/browse/OBSINTA-1343) | [1344](https://stage-redhat.atlassian.net/browse/OBSINTA-1344) | [1345](https://stage-redhat.atlassian.net/browse/OBSINTA-1345) | [1346](https://stage-redhat.atlassian.net/browse/OBSINTA-1346) | [1347](https://stage-redhat.atlassian.net/browse/OBSINTA-1347) |
| LEADS-205 | [1348](https://stage-redhat.atlassian.net/browse/OBSINTA-1348) | [1349](https://stage-redhat.atlassian.net/browse/OBSINTA-1349) | [1350](https://stage-redhat.atlassian.net/browse/OBSINTA-1350) | [1351](https://stage-redhat.atlassian.net/browse/OBSINTA-1351) | [1352](https://stage-redhat.atlassian.net/browse/OBSINTA-1352) | [1353](https://stage-redhat.atlassian.net/browse/OBSINTA-1353) | [1354](https://stage-redhat.atlassian.net/browse/OBSINTA-1354) |
| LEADS-230 | [1355](https://stage-redhat.atlassian.net/browse/OBSINTA-1355) | [1356](https://stage-redhat.atlassian.net/browse/OBSINTA-1356) | [1357](https://stage-redhat.atlassian.net/browse/OBSINTA-1357) | [1358](https://stage-redhat.atlassian.net/browse/OBSINTA-1358) | [1359](https://stage-redhat.atlassian.net/browse/OBSINTA-1359) | [1360](https://stage-redhat.atlassian.net/browse/OBSINTA-1360) | [1361](https://stage-redhat.atlassian.net/browse/OBSINTA-1361) |
| OBSINTA-1329 | [1362](https://stage-redhat.atlassian.net/browse/OBSINTA-1362) | [1363](https://stage-redhat.atlassian.net/browse/OBSINTA-1363) | [1364](https://stage-redhat.atlassian.net/browse/OBSINTA-1364) | [1365](https://stage-redhat.atlassian.net/browse/OBSINTA-1365) | [1366](https://stage-redhat.atlassian.net/browse/OBSINTA-1366) | [1367](https://stage-redhat.atlassian.net/browse/OBSINTA-1367) | [1368](https://stage-redhat.atlassian.net/browse/OBSINTA-1368) |

### Summary Dashboard

| Issue | Qwen 3.6 35B | Qwen3-Coder 30B | Opus 4.6 | Sonnet 4.6 | Gemma4 31B | MiniMax M2.5 | DeepSeek R1 32B |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| OBSINTA-1176 | FAIL | FAIL | **PASS** | **PASS** | FAIL | **PASS** | FAIL |
| ACM-35375 | PARTIAL | FAIL | **PASS** | **PASS** | FAIL | PARTIAL | PARTIAL |
| OCPBUGS-45921 | FAIL | FAIL | **PASS** | **PASS** | PARTIAL | FAIL | FAIL |
| LEADS-205 | PARTIAL | FAIL | **PASS** | **PASS** | FAIL | **PASS** | **PASS** |
| LEADS-230 | PARTIAL | FAIL | **PASS** | **PASS** | FAIL | PARTIAL | FAIL |
| OBSINTA-1329 | PARTIAL | FAIL | **PASS** | **PASS** | FAIL | skipped | **PASS** |
| **Score** | **0/6** | **0/6** | **6/6** | **6/6** | **0/6** | **2/5** | **2/6** |

### Detailed Results

Each run captures the following metrics:

| Field | Description |
|-------|-------------|
| **Jira Ticket** | Stage Jira ticket key |
| **Model** | Model name and provider |
| **Command** | Exact `opencode run` command used |
| **Verdict** | PASS / FAIL |
| **Fix Accuracy** | exact match / equivalent approach / different approach / wrong |
| **Root Cause Match** | Did investigation identify the same root cause as the human? |
| **Files Touched Accuracy** | Correct files modified vs human fix (extra/missing files) |
| **Phase Reached** | Last phase completed (0-11) before success or failure |
| **Failure Type** | ENVIRONMENT / BUILD / TEST / PUSH / OTHER |
| **Tool Call Count** | Total tool calls consumed |
| **Time Taken** | Wall-clock duration (minutes) |
| **Tokens Used** | Input + output tokens |
| **Plan Quality** | Did the plan match the actual fix approach? (HIGH/MEDIUM/LOW) |
| **Regression Test** | Was a regression test written? Quality vs human test |
| **Hallucination** | Did the agent hallucinate about APIs, files, or functions? |
| **Context Window %** | How much of the context window was consumed |
| **Cost Estimate** | Token cost in $ (relevant for Vertex AI models) |
| **PR Link** | Link to the created PR (if any) |
| **Notes** | Observations, interesting behaviors |

---

### Run 1: OBSINTA-1176 × Claude Opus 4.6 (Calibration)

| Field | Value |
|-------|-------|
| **Jira Ticket** | [OBSINTA-1329](https://stage-redhat.atlassian.net/browse/OBSINTA-1329) |
| **Model** | Claude Opus 4.6 (Vertex AI) |
| **Command** | `opencode run --agent fix-investigate -m google-vertex-anthropic/claude-opus-4-6@default "Investigate Jira ticket OBSINTA-1329. Follow the skill."` |
| **Verdict** | **PASS** — full pipeline: investigate → implement → PR → Jira |
| **Fix Accuracy** | **Exact match** — identical approach to human PR #38 |
| **Root Cause Match** | **YES** — correctly identified `NewHTTPClientWithConfig` ignoring `apiConfig.RoundTripper` |
| **Files Touched Accuracy** | **Exact** — `pkg/alertmanager/loader.go` + `pkg/alertmanager/loader_test.go` (human also changed `go.mod` but that's automatic) |
| **Phase Reached** | Investigation: 4/4 complete. Implementation: 11/11 complete |
| **Failure Type** | N/A — full success |
| **Tool Call Count** | Investigation: ~25 calls. Implementation: ~30 calls |
| **Time Taken** | Investigation: 8 min. Implementation: 3 min. Total: ~11 min |
| **Tokens Used** | TBD (need to extract from OpenCode session) |
| **Plan Quality** | **HIGH** — plan matches human fix exactly. Includes alternatives considered, risk assessment, specific code change with before/after |
| **Regression Test** | **YES** — 3 tests: `UsesRoundTripper` (trackingRoundTripper pattern), `NilRoundTripper` (fallback), invalid URL handling. Higher quality than human PR (human PR had no new tests). All 10 tests pass (7 existing + 3 new) |
| **Hallucination** | **None** — all API references verified via `go doc`, correct function signatures |
| **Context Window %** | ~30% estimated (small repo, focused investigation) |
| **Cost Estimate** | ~$2-5 (Vertex AI Opus pricing, ~13 min session) |
| **PR Link** | [rajusem/obs-mcp#1](https://github.com/rajusem/obs-mcp/pull/1) |
| **Notes** | Calibration run. Three env issues found and fixed: (1) Go module cache not in allowlist — added `~/.gvm/*`. (2) Todos tool fails in non-interactive mode — fixed with `--dangerously-skip-permissions` for eval. (3) PTY needed — `script -q` wrapper. Jira labels swapped to `bot-ready-for-review`. All exit gates passed. |

#### Fix Plan Branch
- **Branch**: [`OBSINTA-1329/alertmanager-transport-config-ignored`](https://github.com/rajusem/obs-mcp/tree/OBSINTA-1329/alertmanager-transport-config-ignored)
- **Plan file**: [`.autofix/OBSINTA/OBSINTA-1329/fix-plan.md`](https://github.com/rajusem/obs-mcp/blob/OBSINTA-1329/alertmanager-transport-config-ignored/.autofix/OBSINTA/OBSINTA-1329/fix-plan.md)

#### Calibration Learnings
1. **settings.json needs Go module cache** — added `external_directory(/Users/rzalavad/.gvm/*)`
2. **`--dangerously-skip-permissions` needed for eval** — Todos tool fails without it; safe for eval on forked repos (sensitive file blocklist is in SKILL bash script, not permissions)
3. **`opencode run` needs PTY** — `script -q <logfile>` wrapper required
4. **JIRA credentials via export** — `set -a && source .env && set +a` before `opencode run`
5. **Resilience instruction added to fix-implement agent** — "If Todos fails, continue without it"
6. **`task: deny` kept in fix-implement** — reviewed by 3 experts; `task: allow` would enable unwanted sub-agent spawning for smaller models
