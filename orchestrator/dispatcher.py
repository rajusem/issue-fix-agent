import json
import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent / "state"
STATE_FILE = STATE_DIR / "dispatch_state.json"
LOGS_DIR = Path(__file__).parent / "logs"


class Dispatcher:
    def __init__(self, config: Config):
        self.config = config
        self.state = self._load_state()

    def dispatch(
        self, ticket_key: str, agent: str, prompt: str, ttl_minutes: int
    ) -> int | None:
        if self.config.dry_run:
            log.info("[DRY RUN] Would dispatch %s for %s", agent, ticket_key)
            return None

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        log_file = str(LOGS_DIR / f"{ticket_key}-{agent}-{timestamp}.log")

        with open(log_file, "w") as lf:
            proc = subprocess.Popen(
                ["timeout", f"{ttl_minutes}m",
                 "opencode", "run", "--agent", agent, prompt],
                stdout=lf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        self.state[ticket_key] = {
            "pid": proc.pid,
            "agent": agent,
            "started_at": datetime.utcnow().isoformat(),
            "ttl_minutes": ttl_minutes,
            "log_file": log_file,
        }
        self._save_state()
        log.info("Dispatched %s for %s (PID %d, TTL %dm)",
                 agent, ticket_key, proc.pid, ttl_minutes)
        return proc.pid

    def recover_stale(self, jira) -> list[str]:
        recovered = []
        for key, record in list(self.state.items()):
            pid = record["pid"]
            if not self._is_alive(pid):
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
                del self.state[key]
            elif self._is_stale(record):
                log.warning("%s: agent %s (PID %d) exceeded TTL — killing",
                            key, record["agent"], pid)
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                del self.state[key]
                recovered.append(key)

        self._save_state()
        return recovered

    def is_tracked(self, ticket_key: str) -> bool:
        if ticket_key not in self.state:
            return False
        return self._is_alive(self.state[ticket_key]["pid"])

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
                return "opencode" in cmdline
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
