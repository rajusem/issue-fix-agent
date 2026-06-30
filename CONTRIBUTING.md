# Contributing to Issue-Fix Agent

Thanks for your interest in contributing! This project builds an autonomous
bug-fixing pipeline using OpenCode + OpenShell on OpenShift.

## Getting Started

1. Read the [README](README.md) for project overview
2. Follow [docs/quickstart-local.md](docs/quickstart-local.md) to set up locally
3. Review [docs/Architecture.md](docs/Architecture.md) for system design

## Project Structure

```
.opencode/agents/     # Agent definitions (YAML frontmatter + markdown)
.opencode/skills/     # Skill playbooks (SKILL.md — multi-phase workflows)
.opencode/plugins/    # Safety hooks (block destructive commands)
orchestrator/         # Python watcher + dispatcher
policies/             # OpenShell sandbox policies (YAML)
manifests/            # K8s deployment manifests
docs/                 # Current documentation
eval/                 # Model evaluation results
```

## Development Workflow

### Prerequisites

- OpenCode v1.17.11+ (`npm i -g opencode`)
- Python 3.11+ with `uv` or `pip`
- `gh` CLI authenticated
- Jira API token (for MCP integration)

### Running Locally

```bash
# Install deps
uv pip install -r orchestrator/requirements.txt

# Set credentials
cp .env.example .env  # edit with your tokens

# Run a single agent
set -a && source .env && set +a
opencode run --agent fix-investigate \
  --dangerously-skip-permissions \
  -m ollama/deepseek-r1:32b \
  "Investigate Jira ticket YOUR-TICKET. Follow the skill."

# Run the watcher (dry run)
python -m orchestrator.watcher --dry-run
```

## What to Contribute

### Good First Issues

- Add unit tests for `orchestrator/` (currently zero test coverage)
- Add retry with exponential backoff to `jira_client.py`
- Improve health check (HTTP endpoint instead of file-based probe)

### Skill Improvements

Skills are in `.opencode/skills/*/SKILL.md`. Each is a 300+ line
markdown playbook guiding agents through phases.

When modifying skills:
- Test with at least Claude Sonnet AND one open model (DeepSeek R1)
- Smaller models (30-35B) struggle with long playbooks — keep instructions concise
- Run the eval script to benchmark: `bash eval/run-eval.sh`

### Agent Definitions

Agents are in `.opencode/agents/*.md` with YAML frontmatter:

```yaml
---
description: "What this agent does"
model: google-vertex-anthropic/claude-opus-4-6@default
steps: 200
permission:
  read: allow
  edit: allow
  bash: allow
  task: deny
---
```

The `model:` field is the design-time default — the dispatcher overrides
it at runtime with the `FIX_MODEL` config value.

### Sandbox Policies

Policies are in `policies/*.yaml`. Each agent type has its own policy
controlling filesystem access and network endpoints.

When adding a new network endpoint:
- Add to ALL 4 policy files (fix-investigate, fix-implement, review, review-fix)
- Test with `openshell sandbox create --policy policies/<name>.yaml`
- Keep policies restrictive — only allow what's needed

## Code Standards

### Python (orchestrator/)

- Type hints on all functions
- No `# type: ignore` or `# noqa` — fix the underlying issue
- Follow existing patterns in `watcher.py` and `jira_client.py`

### Markdown (skills, agents, docs)

- Skills: follow the existing phase structure (Phase N: Title, steps, code blocks)
- Agent definitions: YAML frontmatter + markdown body
- Docs: practical, concise — no aspirational content

### Commits

```bash
# Format: conventional commits with Signed-off-by
git commit -s -m "feat: add retry logic to jira_client"
git commit -s -m "fix: handle ADF format in comment parsing"
git commit -s -m "docs: update quickstart with new model"
```

- Use `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`
- Always sign off with `-s` flag
- No `Co-Authored-By` — use `Signed-off-by` only

### What NOT to Commit

- `.env` files (secrets)
- `.opencode/opencode.json` (LiteMaaS API key)
- `target-repo/` or `.autofix/` (eval/agent runtime artifacts)
- `__pycache__/` or `*.pyc`
- Large binary files or model weights

## Testing

### Manual Testing

Currently no automated test suite. Test manually:

1. **Skill changes**: Run `opencode run --agent <agent> -m <model> "test prompt"`
2. **Watcher changes**: Run `python -m orchestrator.watcher --dry-run`
3. **Policy changes**: Run `openshell sandbox create --policy <policy> -- <command>`

### PLAN_IN_PR Flag

When testing skills that handle `.autofix/` plan files, test both modes:
- `PLAN_IN_PR=true`: plan committed to branch, included in PR
- `PLAN_IN_PR=false`: plan in Jira comment only, not in PR

### Model Evaluation

For skill or agent changes that affect model behavior:

```bash
# Run eval against a known bug
bash eval/run-eval.sh OBSINTA-XXXX "model/id" "model-name"
```

See `eval/README.md` for the full evaluation methodology and results.

## Review Process

Before submitting changes, run through this checklist:

- [ ] No secrets in committed files (check `.gitignore`)
- [ ] Skills tested with at least one model
- [ ] Agent permissions are minimal (deny by default)
- [ ] Sandbox policies are restrictive (allow only needed endpoints)
- [ ] Docs updated if behavior changed
- [ ] Commit message follows conventional format with `-s`

For significant changes (new agents, skill rewrites, architecture changes):
request review from Architecture, PE, and AI expert perspectives before merging.

## Questions?

- Architecture: See `docs/Architecture.md`
- Deployment: See `docs/deploy-openshift.md`
- Model results: See `eval/README.md`
- Historical decisions: See `docs/archive/`
