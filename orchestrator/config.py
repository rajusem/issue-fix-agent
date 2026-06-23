import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    jira_site: str
    jira_username: str
    jira_api_token: str
    github_token: str
    watched_projects: list[str]
    allowed_repo_hosts: list[str]
    skill_url_allowlist: list[str]
    knowledge_repo_allowlist: list[str]
    bot_service_account: str
    fix_model: str
    investigate_ttl: int
    implement_ttl: int
    review_model: str
    review_ttl: int
    review_fix_model: str
    review_fix_ttl: int
    review_fix_max_cycles: int
    max_concurrent_fix: int
    max_concurrent_review: int
    max_concurrent_review_fix: int
    max_fix_retries: int
    plan_approval_timeout_hours: int
    audit_enabled: bool
    audit_max_iterations: int
    audit_skip_simple: bool
    audit_model: str
    rtk_enabled: bool
    dry_run: bool
    sandbox_enabled: bool
    slack_webhook_url: str | None
    watcher_ttl: int
    jira_poll_interval: int


def load_config(base_dir: Path | None = None) -> Config:
    if base_dir is None:
        base_dir = Path(__file__).parent.parent

    env_path = base_dir / "config" / "config.env"
    if env_path.exists():
        load_dotenv(env_path)

    projects_path = base_dir / "config" / "projects.json"
    if not projects_path.exists():
        print(f"FATAL: {projects_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(projects_path) as f:
        projects = json.load(f)

    config = Config(
        jira_site=os.environ.get("JIRA_SITE", ""),
        jira_username=os.environ.get("JIRA_USERNAME", ""),
        jira_api_token=os.environ.get("JIRA_API_TOKEN", ""),
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        watched_projects=projects.get("watched_projects", []),
        allowed_repo_hosts=projects.get("allowed_repo_hosts", []),
        skill_url_allowlist=projects.get("skill_url_allowlist", []),
        knowledge_repo_allowlist=projects.get("knowledge_repo_allowlist", []),
        bot_service_account=projects.get("bot_service_account", ""),
        fix_model=os.environ.get("FIX_MODEL", "claude-opus-4-6"),
        investigate_ttl=int(os.environ.get("INVESTIGATE_SESSION_TTL", "90")),
        implement_ttl=int(os.environ.get("IMPLEMENT_SESSION_TTL", "150")),
        review_model=os.environ.get("REVIEW_MODEL", "claude-sonnet-4-6"),
        review_ttl=int(os.environ.get("REVIEW_SESSION_TTL", "30")),
        review_fix_model=os.environ.get("REVIEW_FIX_MODEL", "claude-opus-4-6"),
        review_fix_ttl=int(os.environ.get("REVIEW_FIX_SESSION_TTL", "45")),
        review_fix_max_cycles=int(os.environ.get("REVIEW_FIX_MAX_CYCLES", "3")),
        max_concurrent_fix=int(os.environ.get("MAX_CONCURRENT_FIX_SESSIONS", "4")),
        max_concurrent_review=int(os.environ.get("MAX_CONCURRENT_REVIEW_SESSIONS", "2")),
        max_concurrent_review_fix=int(os.environ.get("MAX_CONCURRENT_REVIEW_FIX_SESSIONS", "2")),
        max_fix_retries=int(os.environ.get("MAX_FIX_RETRIES", "2")),
        plan_approval_timeout_hours=int(os.environ.get("PLAN_APPROVAL_TIMEOUT_HOURS", "48")),
        audit_enabled=os.environ.get("AUDIT_ENABLED", "true").lower() == "true",
        audit_max_iterations=int(os.environ.get("AUDIT_MAX_ITERATIONS", "3")),
        audit_skip_simple=os.environ.get("AUDIT_SKIP_SIMPLE", "true").lower() == "true",
        audit_model=os.environ.get("AUDIT_MODEL", "claude-sonnet-4-6"),
        rtk_enabled=os.environ.get("RTK_ENABLED", "false").lower() == "true",
        dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
        sandbox_enabled=os.environ.get("SANDBOX_ENABLED", "false").lower() == "true",
        slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
        watcher_ttl=int(os.environ.get("WATCHER_SESSION_TTL", "15")),
        jira_poll_interval=int(os.environ.get("JIRA_POLL_INTERVAL", "20")),
    )

    return config


def validate_config(config: Config, base_dir: Path | None = None) -> None:
    if base_dir is None:
        base_dir = Path(__file__).parent.parent
    errors = []

    if not config.jira_site:
        errors.append("JIRA_SITE is required (set in config.env or environment)")
    if not config.jira_username:
        errors.append("JIRA_USERNAME is required (set in environment)")
    if not config.jira_api_token:
        errors.append("JIRA_API_TOKEN is required (set in environment)")
    if not config.github_token:
        errors.append("GITHUB_TOKEN is required (set in environment)")
    if not config.watched_projects:
        errors.append("watched_projects is empty in projects.json")
    if not config.allowed_repo_hosts:
        errors.append("allowed_repo_hosts is empty in projects.json — all tickets will be skipped")

    if config.sandbox_enabled:
        import shutil
        if not shutil.which("openshell"):
            errors.append("SANDBOX_ENABLED=true but openshell binary not found in PATH")
        policies_dir = base_dir / "policies" if base_dir else Path("policies")
        for agent in ["fix-investigate", "fix-implement", "review", "review-fix"]:
            policy = policies_dir / f"{agent}.yaml"
            if not policy.exists():
                errors.append(f"Policy file missing: {policy}")

    if errors:
        for err in errors:
            print(f"CONFIG ERROR: {err}", file=sys.stderr)
        sys.exit(1)
