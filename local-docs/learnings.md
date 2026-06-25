# Learnings: Issue-Fix Agent Development

> Captured during development, testing, and deployment (2026-06-17 to 2026-06-24)
> These are hard-won lessons from building an enterprise AI agent pipeline.

---

## 1. LLM Agents Cannot Enforce Soft Gates

**What happened**: We added a "STOP HERE, EXIT, Do NOT proceed to Phase 5"
instruction in the middle of a 700-line skill file. The agent ignored it
across 3 test runs and proceeded to create PRs without human approval.

**Root cause**: LLM agents treat ALL instructions probabilistically. A
1,000-line skill file with strong forward momentum (Phase 0→1→2→...→10)
overwhelms any mid-flow "stop" instruction.

**Fix**: Split the skill into two separate files — `issue-investigate`
(Phases 0-4) and `issue-implement` (Phases 5-11). The investigation
skill literally doesn't contain implementation phases. The watcher
controls which skill is dispatched.

**Lesson**: If you need a hard gate, make it structural (separate files,
separate agents, orchestrator-controlled dispatch), not instructional.

---

## 2. Open Models Need Explicit Configuration in OpenCode

**What happened**: All local Ollama models (Gemma4, Qwen3, Qwen3-Coder)
failed at tool calling. They either used XML format (`<function=...>`)
or couldn't find MCP tools at all.

**Root cause**: Without a custom `ollama` provider block in
`opencode.json`, OpenCode didn't route tool definitions through the
OpenAI-compatible API. Tools were described as text in the system
prompt, and models tried to "simulate" tool calls.

**Fix**: Add explicit provider config:
```json
"ollama": {
  "npm": "@ai-sdk/openai-compatible",
  "options": { "baseURL": "http://localhost:11434/v1" },
  "models": { "model-name": { "contextWindow": 128000 } }
}
```

**Lesson**: Always register custom providers in `opencode.json` with
the correct SDK. Don't assume auto-discovery works.

---

## 3. Ollama Default Context Window (2048) Breaks Agent Mode

**What happened**: Qwen3-Coder worked fine without `--agent` flag but
reverted to XML tool format with `--agent fix-investigate`.

**Root cause**: Ollama defaults to `num_ctx=2048`. In agent mode,
OpenCode loads the agent definition + skill file + AGENTS.md (~9K
tokens), overflowing the context. The model falls back to its
training-time XML function calling format.

**Fix**: Custom Modelfile with `num_ctx 32768`:
```
FROM qwen3-coder:30b
PARAMETER num_ctx 32768
```

**Lesson**: When using local models in agent mode, always set
`num_ctx` large enough for the system prompt + skill file + context.

---

## 4. Jira v3 API Returns ADF, Not Plain Text

**What happened**: The watcher couldn't parse ticket descriptions or
comment fields. `**Repository**: https://...` returned as
`*Repository*: https://...` or plain `Repository: https://...`.

**Root cause**: Jira v3 returns descriptions in Atlassian Document
Format (ADF) — nested JSON, not markdown. Bold `**text**` becomes
wiki markup `*text*` or plain text after ADF conversion.

**Fix**: Match all 3 patterns in field extraction:
```python
for pattern in [
    rf"\*\*{field}\*\*\s*:\s*(.+)",  # markdown bold
    rf"\*{field}\*\s*:\s*(.+)",      # wiki markup bold
    rf"^{field}\s*:\s*(.+)",          # plain text
]:
```

**Lesson**: Never assume Jira returns markdown. Parse ADF explicitly
and handle all format variants.

---

## 5. Jira v3 Search API Changed (Deprecated /search)

**What happened**: `atlassian-python-api`'s `jql()` method returned
`"The requested API has been removed"`.

**Root cause**: Jira deprecated `/rest/api/3/search` and moved to
`/rest/api/3/search/jql`. The Python library hadn't updated yet.

**Fix**: Use raw GET with the new endpoint:
```python
self.jira.get("rest/api/3/search/jql", params={"jql": jql, "fields": "..."})
```

**Lesson**: Pin API versions and test against live Jira, not mocked
responses. Atlassian deprecates APIs frequently.

---

## 6. Jira `update_issue_field` Wraps in Wrong JSON Structure

**What happened**: Label swaps failed with "Field 'update' cannot be
set" error.

**Root cause**: `atlassian-python-api`'s `update_issue_field()` wraps
the body in `{"fields": ...}`. Our `{"update": {"labels": [...]}}` became
`{"fields": {"update": {"labels": [...]}}}` — which Jira rejects.

**Fix**: Use raw PUT:
```python
self.jira.put(f"rest/api/3/issue/{key}", data={"update": {"labels": ops}})
```

**Lesson**: When using API wrapper libraries, verify the exact HTTP
request they send. Sometimes raw REST is safer than the SDK.

---

## 7. CronJob Kills Subprocess Children

**What happened**: Agent processes dispatched via `subprocess.Popen`
were killed immediately when the CronJob pod exited.

**Root cause**: Kubernetes kills ALL processes in a pod's cgroup when
the main process exits. CronJob pods are ephemeral — they exit after
one cycle. Agents with 90-150 min TTL can't survive in a 20-min pod.

**Fix**: Use a Deployment with `--loop` mode instead of CronJob.
Single-replica pod stays alive, agents run as subprocess children
within the same cgroup.

**Lesson**: On K8s, if you need long-running child processes, use a
Deployment (persistent pod), not a CronJob (ephemeral pod).

---

## 8. Container Image Architecture Mismatch (ARM vs AMD64)

**What happened**: Pod showed `Exec format error` on OpenShift.

**Root cause**: Image built on Apple Silicon (ARM64) but OpenShift
runs AMD64. `podman build` defaults to host architecture.

**Fix**: `podman build --platform linux/amd64`

**Lesson**: Always specify `--platform` when building for a different
architecture cluster.

---

## 9. OpenShift SCC Blocks Non-Compliant Pods

**What happened**: Pod failed with "unable to validate against any
security context constraint" — `fsGroup: 1001` rejected.

**Fix**: Use OpenShift-compatible security context:
```yaml
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
containers:
  - securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
```

**Lesson**: Always design containers for OpenShift's `restricted-v2`
SCC. Don't hardcode UIDs, drop all capabilities, set seccomp profile.

---

## 10. OpenCode Needs Writable Directories in Container

**What happened**: Agent failed with `PermissionDenied: FileSystem.open
(/opt/app-root/src/.local/share/opencode/log/opencode.log)`.

**Root cause**: OpenCode writes logs and state to `~/.local/share/opencode/`
and `~/.config/opencode/`. In a non-root container, these directories
don't exist or aren't writable.

**Fix**: Pre-create and chmod in Containerfile:
```dockerfile
RUN mkdir -p /opt/app-root/src/.local/share/opencode/log \
    /opt/app-root/src/.config/opencode && \
    chmod -R 777 /opt/app-root/src/.local /opt/app-root/src/.config
```

**Lesson**: Check what directories your CLI tools write to and
pre-create them in the container image with correct permissions.

---

## 11. Git Identity Must Be Pre-Configured in Container

**What happened**: Agent tried to commit but failed with `unable to
auto-detect email address`. This wasted 2 tool calls fixing it,
leaving too few for the push + Jira steps.

**Fix**: Set git identity in Containerfile:
```dockerfile
RUN git config --system user.email "issue-fix-agent@bot.local" && \
    git config --system user.name "issue-fix-agent"
```

**Lesson**: Pre-configure every tool's identity/config in the container.
Agents shouldn't spend tool calls on setup tasks.

---

## 12. Open Models Over-Investigate Without Guidance

**What happened**: Qwen 3.6 on the cluster used 95 tool calls (vs
6-10 for Claude) — reading every test file, tracing the full codebase,
re-reading the skill file. Ran out of steps before posting the plan.

**Fix**: Two changes:
1. Set `steps: 120` in agent definition (hard limit on tool calls)
2. Add focus directive: "Budget ~30 tool calls for investigation,
   ~10 for plan writing and posting"

**Lesson**: Open models need explicit budgeting guidance. Claude
self-regulates; smaller models need guardrails on exploration depth.

---

## 13. Agent Must Know Its Working Directory on K8s

**What happened**: Agent cloned repo to `/tmp/repo/` but ran `git
commit` from `/app/` (watcher's directory). Failed with "not a git
repository".

**Root cause**: Locally, OpenCode's working directory was the project
root. On K8s, the watcher runs from `/app/`, and the cloned repo is
in `/tmp/`. The agent didn't `cd` back to the repo for git commands.

**Fix**: Add explicit instruction in agent definition: "All git
commands must run from INSIDE the cloned repo. Use `cd <repo-dir>`."

**Lesson**: Agents that work locally may break on K8s due to different
working directory assumptions. Make directory context explicit.

---

## 14. Models.corp is Internal-Only (No Cluster Access)

**What happened**: Tested from two OpenShift clusters — both returned
NXDOMAIN for `apps.int.stc.ai.prod.us-east-1.aws.paas.redhat.com`.

**Root cause**: Models.corp runs on Red Hat's internal network.
`openshiftapps.com` managed clusters use public DNS and can't resolve
internal hostnames.

**Solution**: Use LiteMaaS instead (`litellm-litemaas.apps.prod.rhoai.
rh-aiservices-bu.com`) — public DNS, accessible from any cluster.

**Lesson**: "Internal" services may not be reachable from managed
cloud clusters. Always test network connectivity from an actual pod
before designing around an endpoint.

---

## 15. LiteMaaS API Keys Are Model-Scoped

**What happened**: Tried 10 model names on LiteMaaS, only 2 worked.
Error: "key not allowed to access model".

**Lesson**: LiteMaaS keys are scoped to specific models. Request
access to the models you need, not just any key.

---

## 16. Sonnet Matches Opus for Investigation

**What happened**: All investigation tests used Claude Opus ($15/ticket).
When we finally tested Sonnet ($5/ticket), it found the same root
cause AND the original fix commit — slightly better than Opus.

**Lesson**: Don't assume you need the most expensive model. Benchmark
the cheaper alternative before committing to the premium tier.

---

## 17. The Review Process Catches Real Issues

**What happened**: We ran 3-round architecture + PE + SDLC + agent
expert reviews on every major design decision. Each round caught
genuine issues:
- CronJob lifecycle mismatch (would have been a production outage)
- Secrets in CLI args (security vulnerability)
- `--no-keep` race condition (would lose artifacts)
- Sonnet never benchmarked (quality risk)

**Lesson**: Multi-perspective review (even with AI reviewers) catches
issues that single-perspective thinking misses. The cost of review
is tiny compared to the cost of a production incident.

---

## 18. OpenCode `external_directory` Permission Blocks Silently

**What happened**: Agent cloned repo to `/tmp/`, then Glob/Grep
operations failed with "ripgrep execution failed". The agent died
after ~20 tool calls every time.

**Root cause**: OpenCode's `external_directory` permission is NOT
covered by `--dangerously-skip-permissions`. Accessing files outside
the working directory requires explicit permission. When the session
has no user, the permission prompt hangs and the session dies.

**Fix**: Set `--dir /tmp` on `opencode run` so `/tmp` is the working
directory. Clone repos into the working directory (not "external").

**Lesson**: `--dangerously-skip-permissions` doesn't mean ALL
permissions are skipped. External directory access has its own gate.

---

## 19. Container Image Must Include Full Toolchain

**What happened**: Implementation agent tried to run `go test` but
Go wasn't installed in the container. Spent all its steps trying to
install Go, ran out before creating the PR.

**Fix**: Add `golang` to Containerfile's `dnf install`.

**Lesson**: Agent containers need the full development toolchain for
the target repos (Go, Python, Node, etc.). The agent can't install
tools at runtime — it wastes tool calls and may not have permission.

---

## 20. OpenCode Config Discovery is Working-Directory Relative

**What happened**: With `--dir /tmp`, OpenCode looked for config at
`/tmp/.opencode/opencode.json` and `/tmp/opencode.json`, not at
`/app/.opencode/opencode.json`. LiteMaaS provider wasn't found.

**Fix**: Symlink all config files from `/app/` to `/tmp/` via an
init command in the Deployment spec.

**Lesson**: When changing OpenCode's working directory, ALL config
files must be accessible from the new directory.

---

## 21. Agent Comment Format Varies Between Models

**What happened**: Watcher's `_extract_fix_branch` required comments
to contain "Fix Plan" AND "APPROVED". Qwen 3.6 posted the plan with
different wording — branch extraction returned None.

**Fix**: Relaxed the filter to match any comment with "Plan/plan"
AND "Branch/branch".

**Lesson**: Don't rely on exact wording from LLM agents. Parse
comments with loose patterns and validate extracted values instead.

---

## 22. Podman Cache Can Silently Use Stale Images

**What happened**: Build failed (ripgrep version wrong) but `podman
push` still ran — pushing the OLD cached image. Deployed old code
thinking the fix was in.

**Fix**: Always check build output for "COMMIT" before pushing.
Use `--no-cache` for critical rebuilds.

**Lesson**: Build + push in a single `&&` chain. If build fails,
push should NOT run.

---

## 23. OpenShell Sandbox Requires `sandbox` User in Custom Images

**What happened**: Sandbox pod crashed immediately with "sandbox user
'sandbox' not found in image".

**Root cause**: OpenShell sandboxes expect a `sandbox` user (UID 1000)
and group in any custom image used with `--from`. The OpenShell
supervisor runs agent commands as this user.

**Fix**: Add to Containerfile:
```dockerfile
RUN groupadd -g 1000 sandbox && \
    useradd -u 1000 -g sandbox -m -s /bin/bash sandbox
```

Also pre-create writable dirs for the sandbox user's home:
```dockerfile
RUN mkdir -p /home/sandbox/.local/share/opencode/log \
    /home/sandbox/.config/opencode && \
    chmod -R 777 /home/sandbox/.local /home/sandbox/.config
```

**Lesson**: When using custom images with OpenShell `--from`, always
include a `sandbox` user. This is documented but easy to miss.

---

## 24. OpenShell Base Image Has Different OpenCode Version

**What happened**: Sandbox used the base OpenShell image which has an
older opencode that lacks `--dangerously-skip-permissions`.

**Root cause**: `openshell sandbox create -- opencode run ...` runs
inside the sandbox container, which uses the base image's binaries
by default. Our Containerfile installs a newer opencode but the
sandbox doesn't use our image.

**Fix**: Use `--from quay.io/rzalavad/issue-fix-agent:latest` to run
the sandbox with our custom image instead of the base image.

**Lesson**: The sandbox base image and your deployment image are
different. Use `--from` to specify your image when you need custom
binaries or configs inside the sandbox.

---

## 25. Sandbox Config Discovery Requires Init Script

**What happened**: OpenCode inside the sandbox couldn't find agent
definitions, settings.json, or the LiteMaaS provider config.

**Root cause**: Config files are at `/app/` in our image, but OpenCode
looks in the working directory (`/tmp/`). The deployment's symlink
setup (in the pod init command) doesn't run inside sandboxes.

**Fix**: Wrap the opencode command in a bash init script that creates
symlinks before running:
```python
init_script = (
    "mkdir -p /tmp/.opencode && "
    "ln -sf /app/.opencode/agents /tmp/.opencode/agents && "
    "ln -sf /app/.opencode/settings.json /tmp/.opencode/settings.json && "
    'echo "$LITEMAAS_CONFIG" > /tmp/.opencode/opencode.json && '
    f"opencode run {oc_args} '{prompt}'"
)
cmd = ["openshell", "sandbox", "create", "--from", image,
       "--"] + ["bash", "-c", init_script]
```

**Lesson**: Sandbox environments start clean — no init containers,
no volume mounts. All setup must happen in the command itself.

---

## 26. LiteMaaS Config Must Be Injected Into Sandbox via Env Var

**What happened**: Inside the sandbox, the LiteMaaS Secret mount
(`/tmp/litemaas-config/opencode.json`) doesn't exist. OpenCode
failed with `ProviderModelNotFoundError`.

**Root cause**: K8s Secret mounts only exist in the watcher pod.
Sandbox pods are separate — they don't share volume mounts.

**Fix**: Read the LiteMaaS config from the mounted path in the
watcher pod, pass it via an uploaded env file (not `--env` — see
lesson 30), and write it to `/tmp/.opencode/opencode.json` in the
sandbox init script.

**Lesson**: Any config that comes from K8s Secrets must be explicitly
forwarded to sandboxes — they don't inherit volume mounts.

---

## 27. Sandbox Policy Must Include `/dev` for `/dev/null` Access

**What happened**: Bash profile scripts failed with
`/dev/null: Permission denied` inside the sandbox.

**Root cause**: The sandbox policy's `read_write` paths didn't
include `/dev`. Landlock blocked write access to `/dev/null`.

**Fix**: Add `/dev` to `read_write` in all sandbox policies.

**Lesson**: Don't forget device files. `/dev/null`, `/dev/urandom`
are needed by many tools and shell scripts.

---

## 28. Sandbox Network Policy `binaries` Path Must Match Actual Binary Location

**What happened**: OpenCode connected to LiteMaaS but got
`Forbidden: policy_denied`.

**Root cause**: Network policy `binaries` was set to `/sandbox/**`
but opencode runs from `/usr/local/bin/opencode`. The policy
restricts which binaries can make network calls.

**Fix**: Changed `binaries` path from `/sandbox/**` to `/**` in all
policy files. The endpoint restrictions still control WHICH hosts
can be contacted.

**Lesson**: The `binaries` field in OpenShell network policies
controls which executables can make outbound connections, not just
filesystem access. Use `/**` unless you need to restrict specific
binaries from making network calls.

---

## 29. Phase 1B JQL Label Mismatch (`bot-proceed` vs `bot-plan-approved`)

**What happened**: After investigation completed and human approved
the plan, the watcher re-dispatched `fix-investigate` instead of
`fix-implement`. Phase 1B found 0 approved plans.

**Root cause**: Two bugs:
1. Phase 1B JQL searched for `bot-proceed` but the approval label
   was `bot-plan-approved`
2. Phase 1 JQL didn't exclude `bot-proceed` or `bot-plan-approved`,
   so approved tickets were picked up as "new"

**Fix**: Updated Phase 1 to exclude both approval labels. Updated
Phase 1B to accept both `bot-proceed` OR `bot-plan-approved`.

**Lesson**: When adding new labels to a state machine, grep ALL
JQL queries to ensure the new label is properly included/excluded
in every phase. Label name consistency matters.

---

## 30. OpenShell `--env KEY=VALUE` Truncates Values Containing `=`

**What happened**: The Jira API token (`ATATT3x...6w=185E6394`)
was truncated to `ATATT3x...6w=` inside the sandbox. The `185E6394`
after the second `=` was dropped, causing Jira 404 errors.

**Root cause**: OpenShell's `--env` flag parses `KEY=VALUE` by
splitting on `=`. Values containing `=` (common in base64-encoded
tokens and API keys) get truncated.

**Fix**: Use `--upload` to send an env file into the sandbox instead
of `--env` flags. The env file is sourced in the init script:
```python
env_file = self._write_env_file()
cmd = ["openshell", "sandbox", "create",
       "--upload", f"{env_file}:/tmp/sandbox-env", ...]
init_script = "set -a && source /tmp/sandbox-env && set +a && rm -f /tmp/sandbox-env && ..."
```

**Lesson**: Never pass credentials via `--env KEY=VALUE` when values
might contain `=`. Use file upload + source instead.

---

## 31. Env File Deleted Before Sandbox Upload Completes

**What happened**: The env file cleanup timer (5 seconds) deleted
the file before openshell could upload it. Sandbox startup takes
~10-30 seconds (allocate + pull image), so the file was gone.

**Fix**: Increased cleanup timer from 5 seconds to 120 seconds.

**Lesson**: Sandbox creation is async — the upload happens after
image pulls complete. Any temp files needed for `--upload` must
survive the full startup sequence.

---

## 32. Bash `source` Strips JSON Quotes and Expands `$` Variables

**What happened**: The LiteMaaS config JSON stored in the env file
as `LITEMAAS_CONFIG={"$schema":"https://..."}` lost all double
quotes and `$schema` was expanded (to empty string).

**Root cause**: When bash sources a file with `KEY=value`, it
interprets `"` as shell quotes (stripping them) and `$` as
variable expansion.

**Fix**: Single-quote all values in the env file:
```python
escaped = v.replace("'", "'\\''")
f.write(f"{k}='{escaped}'\n")
```

Single quotes prevent all bash interpretation — no quote stripping,
no variable expansion, no globbing.

**Lesson**: Env files sourced by bash need single-quoted values.
Double quotes are NOT safe for JSON content or values with `$`.

---

## 33. Go Proxy Blocked by Sandbox Network Policy

**What happened**: `go test` and `go build` inside the sandbox failed
with `Forbidden` errors when downloading modules from `proxy.golang.org`.

**Root cause**: The sandbox network policies only allowed Jira, GitHub,
LiteMaaS, and Vertex AI endpoints. Go toolchain needs `proxy.golang.org`,
`sum.golang.org`, and `storage.googleapis.com`.

**Fix**: Added Go endpoints to `fix-implement.yaml` and `review-fix.yaml`
sandbox policies.

**Lesson**: Any build toolchain the agent might use needs its package
registry endpoints in the sandbox network policy.

---

## 34. Go Module Cache Not Available in Sandbox

**What happened**: Even with Go proxy endpoints allowed, downloading
500MB+ of modules was slow and consumed agent steps.

**Fix**: Pre-cache Go modules during image build:
```dockerfile
COPY config/go-mod-repos.txt /tmp/go-mod-repos.txt
RUN git clone --depth 1 "$repo" && cd repo && \
    GOMODCACHE=/home/sandbox/go/pkg/mod go mod download && \
    go mod vendor && cp -r vendor /home/sandbox/go/vendor-cache
```

Also set `GOMODCACHE` and `GOFLAGS=-mod=mod` in the sandbox init script.

**Lesson**: Pre-cache build dependencies in the container image for
repos the agent will work on. The `config/go-mod-repos.txt` file
lists repos to pre-cache.

---

## 35. `/home/sandbox/.cache` Permission Denied (Bun/OpenCode)

**What happened**: OpenCode (Bun runtime) failed with
`EACCES: permission denied, mkdir '/home/sandbox/.cache'`.

**Fix**: `chmod 777 /home/sandbox` in Containerfile (was only
chmod-ing subdirectories).

**Lesson**: The sandbox user's entire home directory needs to be
writable — not just specific subdirectories.

---

## 36. Agent-Sandbox Controller Needs Admin ClusterRoleBinding

**What happened**: Sandbox pods stuck in `Provisioning` phase.
OpenShell reported "supervisor session not connected".

**Root cause**: The agent-sandbox-controller couldn't set
`blockOwnerDeletion` on pods/PVCs/services because it lacked
permissions.

**Fix**: Grant admin ClusterRoleBinding to the controller:
```bash
oc create clusterrolebinding sandbox-controller-admin \
  --clusterrole=admin \
  --serviceaccount=agent-sandbox-system:agent-sandbox-controller
```

**Lesson**: The agent-sandbox CRD controller needs broader RBAC
than its default manifest provides on OpenShift.

---

## 37. OpenShell Supervisor Relay Race Condition

**What happened**: Sandbox creation succeeded but SSH connection
failed intermittently with "supervisor session not connected".

**Root cause**: The OpenShell supervisor inside the sandbox pod
isn't ready when the client tries to SSH immediately after creation.
Happens ~50% of the time on clusters where image pull is slow.

**Fix**: Wrap sandbox creation in a retry loop (3 attempts, 15s delay):
```python
retry_cmd = ["bash", "-c",
    "for attempt in 1 2 3; do "
    "\"$@\" && exit 0; "
    "sleep 15; done; exit 1", "--"] + cmd
```

**Lesson**: OpenShell sandbox creation is not guaranteed to succeed
on the first attempt. Always retry with delay.

---

## 38. `--env KEY=VALUE` vs `--upload` vs Base64 for Credentials

**What happened**: Three approaches tried for passing credentials
to sandboxes:
1. `--env KEY=VALUE` — truncates values containing `=`
2. `--upload` env file — fails with "supervisor session not connected"
3. `--env _B64_KEY=<base64>` + decode in init script — works reliably

**Fix**: Base64-encode values containing `=`, `"`, `'`, or `$`:
```python
b64 = base64.b64encode(v.encode()).decode()
env_args.extend(["--env", f"_B64_{k}={b64}"])
# In init script: export K=$(echo "$_B64_K" | base64 -d)
```

**Lesson**: Use base64 encoding for any credential values that
contain shell-special characters. It's more reliable than file
upload (no timing dependency) and handles all special characters.

---

## 39. Investigate Agent Must Checkout Ticket's Branch

**What happened**: Agent cloned the repo (default branch = main)
and found the bug was already fixed. Proposed a wrong fix approach
(ConditionCheck API that doesn't exist).

**Root cause**: The investigate skill didn't checkout the branch
specified in the ticket's `**Branch**:` field. The agent investigated
`main` (where the fix already exists) instead of the target branch.

**Fix**: Added explicit checkout step in the investigate skill:
```bash
git fetch origin <branch> && git checkout <branch>
```

**Lesson**: Always checkout the ticket's specified branch before
investigation. The default branch may have different code.

---

## 40. NetworkPolicy DNS Port is 53, Not 5353

**What happened**: Watcher couldn't resolve any hostnames. All Jira
API calls failed with `NameResolutionError`.

**Root cause**: NetworkPolicy allowed DNS on port 5353 but OpenShift
CoreDNS listens on port 53.

**Fix**: Changed DNS port in networkpolicy.yaml from 5353 to 53.

**Lesson**: OpenShift CoreDNS uses standard port 53, not the mDNS
port 5353. Always verify the actual service port before creating
NetworkPolicies.

---

## Summary: What Makes Enterprise Agent Pipelines Hard

1. **Structural enforcement** > instructional enforcement
2. **Container environment** ≠ local environment (dirs, UIDs, DNS, git)
3. **API libraries** may not match actual API behavior
4. **Open models** need explicit guardrails (steps, focus, context)
5. **Network assumptions** break across cluster boundaries
6. **Every iteration** reveals a new environmental issue
7. **Test on the actual platform** early — local success ≠ cluster success
8. **Config discovery** is path-relative — symlinks needed on K8s
9. **Permission models** have hidden gates (external_directory)
10. **Agent output format** varies — parse loosely, validate strictly
11. **OpenShell sandbox ≠ deployment pod** — different image, no volume
    mounts, no init containers. Everything must be explicit.
12. **Sandbox policies need broad filesystem paths** — `/dev`, `/home`,
    `/app`, `/opt` are all needed beyond the obvious `/tmp` and `/sandbox`.
13. **Network policy `binaries` field** controls which executables can
    make outbound calls — not just filesystem access.
14. **Label state machines need exhaustive JQL audits** — every new
    label must be included/excluded in every phase's query.
15. **Credential injection needs base64** — `--env` truncates `=`,
    `--upload` has timing issues. Base64 encode + decode is reliable.
16. **Pre-cache build deps in the image** — Go modules, npm packages,
    etc. should be cached during `podman build`, not downloaded at runtime.
17. **Retry sandbox creation** — OpenShell supervisor has a startup
    race condition. Always retry with delay.
18. **Checkout the ticket's branch** — agent investigating `main`
    instead of the target branch produces wrong fix plans.
19. **Verify DNS port** — OpenShift CoreDNS is port 53, not 5353.
