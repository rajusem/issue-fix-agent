import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent / "state"
STATE_FILE = STATE_DIR / "dispatch_state.json"
LOGS_DIR = Path(__file__).parent / "logs"
RUNS_DIR = Path(__file__).parent.parent / "runs"
POLICIES_DIR = Path(__file__).parent.parent / "policies"


class Dispatcher:
    def __init__(self, config: Config):
        self.config = config
        self.state = self._load_state()

    def dispatch(
        self, ticket_key: str, agent: str, prompt: str, ttl_minutes: int,
        model: str | None = None,
    ) -> int | None:
        if self.config.dry_run:
            log.info("[DRY RUN] Would dispatch %s for %s (model=%s)",
                     agent, ticket_key, model or "agent-default")
            return None

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        log_file = str(LOGS_DIR / f"{ticket_key}-{agent}-{timestamp}.log")
        sandbox_name = None

        opencode_args = ["--agent", agent,
                         "--dangerously-skip-permissions",
                         "--dir", "/tmp"]
        if model:
            opencode_args.extend(["-m", model])

        timeout_cmd = ["timeout", f"{ttl_minutes}m"]
        if not shutil.which("timeout"):
            timeout_cmd = []

        env_file = None
        if self.config.sandbox_enabled:
            sandbox_name = f"{ticket_key}-{agent}-{uuid.uuid4().hex[:8]}".lower()
            policy_file = str(POLICIES_DIR / f"{agent}.yaml")

            env_args = []
            b64_decode_cmds = []
            for k, v in self._get_env_vars().items():
                if "=" in v or '"' in v or "'" in v or "$" in v:
                    import base64
                    b64 = base64.b64encode(v.encode()).decode()
                    env_args.extend(["--env", f"_B64_{k}={b64}"])
                    b64_decode_cmds.append(
                        f'export {k}=$(echo "$_B64_{k}" | base64 -d)')
                else:
                    env_args.extend(["--env", f"{k}={v}"])

            escaped_prompt = prompt.replace("'", "'\\''")
            oc_args = " ".join(opencode_args)
            b64_init = " && ".join(b64_decode_cmds) + " && " if b64_decode_cmds else ""
            init_script = (
                f"{b64_init}"
                "mkdir -p /tmp/.opencode && "
                "ln -sf /app/.opencode/agents /tmp/.opencode/agents && "
                "ln -sf /app/.opencode/skills /tmp/.opencode/skills && "
                "ln -sf /app/.opencode/plugins /tmp/.opencode/plugins && "
                "ln -sf /app/.opencode/settings.json /tmp/.opencode/settings.json && "
                "ln -sf /app/opencode.json /tmp/opencode.json && "
                "ln -sf /app/AGENTS.md /tmp/AGENTS.md && "
                'echo "$LITEMAAS_CONFIG" > /tmp/.opencode/opencode.json && chmod 600 /tmp/.opencode/opencode.json && '
                "export GOMODCACHE=/home/sandbox/go/pkg/mod && "
                "export GOFLAGS=-mod=mod && "
                f"opencode run {oc_args} '{escaped_prompt}'"
            )

            sandbox_image = os.environ.get(
                "SANDBOX_IMAGE", "quay.io/rzalavad/issue-fix-agent:latest",
            )
            cmd = [
                "openshell", "sandbox", "create",
                "--name", sandbox_name,
                "--from", sandbox_image,
                "--policy", policy_file,
                "--cpu", "2",
                "--memory", "8Gi",
            ] + env_args + ["--"] + timeout_cmd + ["bash", "-c", init_script]
        else:
            opencode_cmd = ["opencode", "run"] + opencode_args + [prompt]
            cmd = timeout_cmd + opencode_cmd

        if self.config.sandbox_enabled:
            retry_cmd = [
                "bash", "-c",
                "for attempt in 1 2 3; do "
                "\"$@\" && exit 0; "
                "echo \"Sandbox attempt $attempt failed, retrying in 15s...\"; "
                f"openshell sandbox delete {sandbox_name} 2>/dev/null || true; "
                "sleep 15; "
                "done; exit 1",
                "--",
            ] + cmd
            cmd = retry_cmd

        with open(log_file, "w") as lf:
            proc = subprocess.Popen(
                cmd,
                stdout=lf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        if env_file:
            threading.Timer(120.0, lambda: _safe_unlink(env_file)).start()

        self.state[ticket_key] = {
            "pid": proc.pid,
            "agent": agent,
            "started_at": datetime.utcnow().isoformat(),
            "ttl_minutes": ttl_minutes,
            "log_file": log_file,
            "sandbox_name": sandbox_name,
        }
        self._save_state()
        log.info("Dispatched %s for %s (PID %d, TTL %dm, sandbox=%s)",
                 agent, ticket_key, proc.pid, ttl_minutes,
                 sandbox_name or "none")
        return proc.pid

    def recover_stale(self, jira) -> list[str]:
        recovered = []
        for key, record in list(self.state.items()):
            pid = record["pid"]
            if not self._is_alive(pid):
                sandbox_name = record.get("sandbox_name")
                if sandbox_name:
                    self._extract_and_cleanup_sandbox(key, record)

                labels = jira.get_labels(key)
                if "bot-in-progress" in labels:
                    log.warning("%s: agent %s (PID %d) crashed — resetting labels",
                                key, record["agent"], pid)
                    jira.swap_labels(
                        key,
                        remove=["bot-in-progress"],
                        add=["bot-fix-failed"],
                    )
                    jira.add_comment(
                        key,
                        f"## Fix Failed\n"
                        f"**Phase**: Agent crashed\n"
                        f"**Agent**: {record['agent']}\n"
                        f"**Log**: {record['log_file']}\n\n"
                        f"To retry, add `bot-retry` label.",
                    )
                    recovered.append(key)
                else:
                    log.info("%s: agent finished (PID %d gone, labels updated)", key, pid)
                    if sandbox_name:
                        self._extract_and_cleanup_sandbox(key, record)
                del self.state[key]
            elif self._is_stale(record):
                log.warning("%s: agent %s (PID %d) exceeded TTL — killing",
                            key, record["agent"], pid)
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                sandbox_name = record.get("sandbox_name")
                if sandbox_name:
                    self._extract_and_cleanup_sandbox(key, record)
                del self.state[key]
                recovered.append(key)

        self._save_state()
        return recovered

    def is_tracked(self, ticket_key: str) -> bool:
        if ticket_key not in self.state:
            return False
        return self._is_alive(self.state[ticket_key]["pid"])

    def _extract_and_cleanup_sandbox(self, ticket_key: str, record: dict) -> None:
        sandbox_name = record.get("sandbox_name")
        if not sandbox_name:
            return

        run_id = f"{ticket_key}-{record['agent']}-{record['started_at'][:10]}"
        run_dir = str(RUNS_DIR / run_id)
        os.makedirs(run_dir, exist_ok=True)

        if self.config.plan_in_pr:
            result = subprocess.run(
                ["openshell", "sandbox", "download", sandbox_name,
                 "/sandbox/.autofix", f"{run_dir}/.autofix"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                log.warning("Artifact download failed for %s: %s",
                            sandbox_name, result.stderr.strip())
            else:
                log.info("Artifacts extracted for %s to %s", ticket_key, run_dir)

        try:
            subprocess.run(
                ["openshell", "sandbox", "delete", sandbox_name],
                capture_output=True, timeout=30,
            )
            log.info("Sandbox %s deleted", sandbox_name)
        except (subprocess.TimeoutExpired, OSError) as e:
            log.error("Failed to delete sandbox %s: %s", sandbox_name, e)

    def _get_env_vars(self) -> dict:
        env = {
            "GITHUB_TOKEN": self.config.github_token,
            "JIRA_USERNAME": self.config.jira_username,
            "JIRA_API_TOKEN": self.config.jira_api_token,
            "JIRA_URL": f"https://{self.config.jira_site}",
            "GOOGLE_CLOUD_PROJECT": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            "ANTHROPIC_VERTEX_PROJECT_ID": os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", ""),
            "VERTEX_LOCATION": os.environ.get("VERTEX_LOCATION", ""),
            "PLAN_IN_PR": str(self.config.plan_in_pr).lower(),
        }
        litemaas = self._read_litemaas_config()
        if litemaas:
            env["LITEMAAS_CONFIG"] = litemaas
        return env

    def _read_litemaas_config(self) -> str | None:
        for path in [
            "/tmp/litemaas-config/opencode.json",
            "/tmp/.opencode/opencode.json",
        ]:
            try:
                with open(path) as f:
                    return f.read().strip()
            except OSError:
                continue
        return None

    def _write_env_file(self) -> str:
        fd, path = tempfile.mkstemp(prefix="sandbox-env-", suffix=".env")
        with os.fdopen(fd, "w") as f:
            for k, v in self._get_env_vars().items():
                escaped = v.replace("'", "'\\''")
                f.write(f"{k}='{escaped}'\n")
        os.chmod(path, 0o600)
        return path

    def _is_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        try:
            cmdline_path = f"/proc/{pid}/cmdline"
            if os.path.exists(cmdline_path):
                with open(cmdline_path) as f:
                    cmdline = f.read()
                return "opencode" in cmdline or "openshell" in cmdline
        except (OSError, PermissionError):
            pass
        return True

    def _is_stale(self, record: dict) -> bool:
        started = datetime.fromisoformat(record["started_at"])
        ttl_with_buffer = record["ttl_minutes"] + 10
        return datetime.utcnow() > started + timedelta(minutes=ttl_with_buffer)

    def _load_state(self) -> dict:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                log.warning("Corrupt state file — starting fresh")
                return {}
        return {}

    def _save_state(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2)


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
