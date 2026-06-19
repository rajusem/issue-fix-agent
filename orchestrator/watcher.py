#!/usr/bin/env python3
"""Issue Fix Agent — Watcher Orchestrator

Runs one Jira polling cycle, dispatches OpenCode agents based on label
state, then exits. Designed to be invoked by cron every JIRA_POLL_INTERVAL
minutes.

Usage:
    python -m orchestrator.watcher [--dry-run]

Or with cron overlap prevention:
    flock -n /tmp/issue-fix-watcher.lock python -m orchestrator.watcher
"""

import argparse
import fcntl
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from .config import Config, load_config, validate_config
from .dispatcher import Dispatcher
from .jira_client import JiraClient
from .models import CycleStats

log = logging.getLogger("watcher")
LOCK_FILE = "/tmp/issue-fix-watcher.lock"


def main():
    parser = argparse.ArgumentParser(description="Issue Fix Agent Watcher")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log actions without executing mutations")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    if args.dry_run:
        config.dry_run = True
    validate_config(config)

    lock_fd = acquire_lock()
    if lock_fd is None:
        log.info("Another watcher cycle is running — exiting")
        sys.exit(0)

    try:
        run_cycle(config)
    finally:
        lock_fd.close()


def acquire_lock():
    try:
        fd = open(LOCK_FILE, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        return None


def check_ttl(cycle_start: float, watcher_ttl: int, min_required: int = 3) -> bool:
    elapsed_min = (time.time() - cycle_start) / 60
    remaining = watcher_ttl - elapsed_min
    return remaining >= min_required


def run_cycle(config: Config) -> CycleStats:
    stats = CycleStats()
    jira = JiraClient(config)
    dispatcher = Dispatcher(config)
    cycle_start = time.time()

    prefix = "[DRY RUN] " if config.dry_run else ""
    log.info("%sCycle started — projects: %s", prefix, config.watched_projects)

    recovered = dispatcher.recover_stale(jira)
    if recovered:
        log.info("Recovered %d stale agents: %s", len(recovered), recovered)

    phases = [
        ("Phase 1: New tickets", phase_new_tickets),
        ("Phase 1B: Plan approval", phase_plan_approval),
        ("Phase 9: Plan timeout", phase_plan_timeout),
    ]

    for name, fn in phases:
        if not check_ttl(cycle_start, config.watcher_ttl):
            log.warning("TTL exhausted — skipping remaining phases")
            break
        try:
            fn(jira, dispatcher, config, stats)
        except Exception as e:
            log.error("Phase '%s' failed: %s", name, e, exc_info=True)
            stats.errors.append(f"{name}: {e}")

    elapsed = int(time.time() - cycle_start)
    log.info("Cycle complete in %ds — %s", elapsed, _stats_summary(stats))
    post_summary(config, stats, elapsed)
    return stats


def phase_new_tickets(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = autofix AND labels NOT IN "
        f"(bot-in-progress, bot-ready-for-review, bot-review-complete, "
        f"bot-review-fix, bot-merged, bot-fix-failed, bot-missing-info, "
        f"no-autofix, bot-cancelled, bot-plan-ready) "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql)
    log.info("Phase 1: Found %d new autofix tickets", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        if not ticket.repo_url:
            log.info("%s: Missing repo URL — adding bot-missing-info", ticket.key)
            jira.swap_labels(ticket.key, remove=[], add=["bot-missing-info"])
            jira.add_comment(
                ticket.key,
                "## Missing Information\n"
                "This ticket is missing the **Repository** URL in the "
                "Agent Configuration section.\n\n"
                "Please add:\n```\n---\n## Agent Configuration\n"
                "**Repository**: https://github.com/org/repo\n"
                "**Branch**: main\n```",
            )
            stats.new_tickets += 1
            continue

        active = _active_fix_count(jira, config)
        if active >= config.max_concurrent_fix:
            log.info("Concurrency limit reached (%d/%d) — skipping remaining",
                     active, config.max_concurrent_fix)
            stats.skipped_concurrency += len(issues) - issues.index(issue)
            break

        if dispatcher.is_tracked(ticket.key):
            log.info("%s: Already tracked — skipping", ticket.key)
            continue

        jira.swap_labels(ticket.key, remove=[], add=["bot-in-progress"])
        jira.add_comment(
            ticket.key,
            f"## Agent Session Started\n"
            f"**Agent**: fix-investigate\n"
            f"**Started**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"**Phase**: Investigation",
        )

        prompt = _build_investigate_prompt(ticket, config)
        dispatcher.dispatch(
            ticket.key, "fix-investigate", prompt, config.investigate_ttl
        )
        stats.new_tickets += 1


def phase_plan_approval(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = bot-plan-ready AND labels = bot-proceed "
        f"AND labels NOT IN (bot-in-progress) "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql)
    log.info("Phase 1B: Found %d approved plans", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        active = _active_fix_count(jira, config)
        if active >= config.max_concurrent_fix:
            log.info("Concurrency limit reached — skipping remaining plans")
            break

        comments = jira.get_comments(ticket.key)
        fix_branch = _extract_fix_branch(comments)
        if not fix_branch:
            log.warning("%s: Could not extract fix branch from comments", ticket.key)
            continue

        jira.swap_labels(
            ticket.key,
            remove=["bot-plan-ready", "bot-proceed"],
            add=["bot-in-progress"],
        )
        jira.add_comment(
            ticket.key,
            f"## Agent Session Started (Implementation)\n"
            f"**Agent**: fix-implement\n"
            f"**Started**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"**Phase**: Implementing approved plan",
        )

        prompt = (
            f"Implement the approved fix plan for {ticket.key}. "
            f"Follow the issue-implement skill. "
            f"Jira Site: {config.jira_site}"
        )
        dispatcher.dispatch(
            ticket.key, "fix-implement", prompt, config.implement_ttl
        )
        stats.plans_dispatched += 1


def phase_plan_timeout(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = bot-plan-ready "
        f"AND labels NOT IN (bot-proceed, bot-fix-failed, bot-in-progress) "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql)
    log.info("Phase 9: Checking %d unapproved plans for timeout", len(issues))

    timeout_hours = config.plan_approval_timeout_hours
    for issue in issues:
        key = issue["key"]
        comments = jira.get_comments(key)
        plan_time = _find_plan_comment_time(comments)
        if plan_time is None:
            continue

        age_hours = (datetime.utcnow() - plan_time).total_seconds() / 3600
        if age_hours > timeout_hours:
            log.info("%s: Plan approval timed out (%.0fh > %dh)",
                     key, age_hours, timeout_hours)
            jira.swap_labels(key, remove=["bot-plan-ready"], add=["bot-fix-failed"])
            jira.add_comment(
                key,
                f"## Plan Approval Timeout\n"
                f"The approved plan has been waiting for human review for "
                f">{timeout_hours} hours without response.\n"
                f"Marking as failed. To retry: add `bot-retry` label.",
            )
            stats.stale_plans += 1


def _active_fix_count(jira: JiraClient, config: Config) -> int:
    projects = ",".join(config.watched_projects)
    jql = f"labels = bot-in-progress AND project IN ({projects})"
    return len(jira.search(jql))


def _build_investigate_prompt(ticket, config: Config) -> str:
    parts = [
        f"Investigate the issue described in Jira ticket {ticket.key}.",
        f"Follow the issue-investigate skill.",
        f"",
        f"Ticket: {ticket.key}",
        f"Repository: {ticket.repo_url}",
        f"Branch: {ticket.branch or 'main'}",
        f"Commit: {ticket.commit or 'none'}",
        f"Skill URLs: {', '.join(ticket.skill_urls) if ticket.skill_urls else 'none'}",
        f"Skill URL Allowlist: {', '.join(config.skill_url_allowlist) if config.skill_url_allowlist else 'none'}",
        f"Allowed Repo Hosts: {', '.join(config.allowed_repo_hosts)}",
        f"Knowledge Repo: {ticket.knowledge_repo or 'none'}",
        f"AUDIT_ENABLED: {config.audit_enabled}",
        f"AUDIT_MAX_ITERATIONS: {config.audit_max_iterations}",
        f"AUDIT_SKIP_SIMPLE: {config.audit_skip_simple}",
        f"AUDIT_MODEL: {config.audit_model}",
        f"RTK_ENABLED: {config.rtk_enabled}",
        f"Jira Site: {config.jira_site}",
    ]
    return "\n".join(parts)


def _extract_fix_branch(comments: list[dict]) -> str | None:
    for comment in reversed(comments):
        body = comment.get("body", "")
        if isinstance(body, dict):
            from .jira_client import adf_to_text
            body = adf_to_text(body)
        if "## Fix Plan" in body and "APPROVED" in body:
            match = re.search(r"\*\*Branch\*\*:\s*`?([^\s`]+)", body)
            if match:
                return match.group(1)
    return None


def _find_plan_comment_time(comments: list[dict]) -> datetime | None:
    for comment in reversed(comments):
        body = comment.get("body", "")
        if isinstance(body, dict):
            from .jira_client import adf_to_text
            body = adf_to_text(body)
        if "## Fix Plan" in body and "APPROVED" in body:
            created = comment.get("created", "")
            if created:
                try:
                    return datetime.fromisoformat(
                        created.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    pass
    return None


def _stats_summary(stats: CycleStats) -> str:
    parts = []
    if stats.new_tickets:
        parts.append(f"new={stats.new_tickets}")
    if stats.plans_dispatched:
        parts.append(f"plans_implemented={stats.plans_dispatched}")
    if stats.stale_plans:
        parts.append(f"stale_plans={stats.stale_plans}")
    if stats.skipped_concurrency:
        parts.append(f"skipped_concurrency={stats.skipped_concurrency}")
    if stats.errors:
        parts.append(f"errors={len(stats.errors)}")
    return ", ".join(parts) if parts else "no activity"


def post_summary(config: Config, stats: CycleStats, elapsed_seconds: int):
    if not config.slack_webhook_url:
        return

    prefix = "[DRY RUN] " if config.dry_run else ""
    text = (
        f"{prefix}Watcher cycle complete ({elapsed_seconds}s)\n"
        f"• New tickets dispatched: {stats.new_tickets}\n"
        f"• Plans implemented: {stats.plans_dispatched}\n"
        f"• Stale plans timed out: {stats.stale_plans}\n"
    )
    if stats.skipped_concurrency:
        text += f"• Skipped (concurrency): {stats.skipped_concurrency}\n"
    if stats.errors:
        text += f"• Errors: {len(stats.errors)}\n"
        for err in stats.errors[:3]:
            text += f"  - {err}\n"

    try:
        import urllib.request
        req = urllib.request.Request(
            config.slack_webhook_url,
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Slack notification failed: %s", e)


if __name__ == "__main__":
    main()
