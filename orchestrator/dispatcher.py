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

        opencode_cmd = ["opencode", "run", "--agent", agent,
                        "--dangerously-skip-permissions"]
        if model:
            opencode_cmd.extend(["-m", model])
        opencode_cmd.append(prompt)

        timeout_cmd = ["timeout", f"{ttl_minutes}m"]
        if not shutil.which("timeout"):
            timeout_cmd = []

        if self.config.sandbox_enabled:
            sandbox_name = f"{ticket_key}-{agent}-{uuid.uuid4().hex[:8]}".lower()
            policy_file = str(POLICIES_DIR / f"{agent}.yaml")
            env_file = self._write_env_file()

            cmd = [
                "openshell", "sandbox", "create",
                "--name", sandbox_name,
                "--policy", policy_file,
                "--cpu", "2",
                "--memory", "8Gi",
                "--env-file", env_file,
                "--",
            ] + timeout_cmd + opencode_cmd
        else:
            env_file = None
            cmd = timeout_cmd + opencode_cmd

        with open(log_file, "w") as lf:
            proc = subprocess.Popen(
                cmd,
                stdout=lf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        if env_file:
            threading.Timer(5.0, lambda: _safe_unlink(env_file)).start()

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

    def _write_env_file(self) -> str:
        fd, path = tempfile.mkstemp(prefix="sandbox-env-", suffix=".env")
        with os.fdopen(fd, "w") as f:
            f.write(f"GITHUB_TOKEN={self.config.github_token}\n")
            f.write(f"JIRA_USERNAME={self.config.jira_username}\n")
            f.write(f"JIRA_API_TOKEN={self.config.jira_api_token}\n")
            f.write(f"JIRA_URL=https://{self.config.jira_site}\n")
            f.write(f"GOOGLE_CLOUD_PROJECT={os.environ.get('GOOGLE_CLOUD_PROJECT', '')}\n")
            f.write(f"ANTHROPIC_VERTEX_PROJECT_ID={os.environ.get('ANTHROPIC_VERTEX_PROJECT_ID', '')}\n")
            f.write(f"VERTEX_LOCATION={os.environ.get('VERTEX_LOCATION', '')}\n")
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
