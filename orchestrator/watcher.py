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
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from pathlib import Path

from .config import Config, load_config, validate_config
from .dispatcher import Dispatcher
from .jira_client import JiraClient
from .models import CycleStats

log = logging.getLogger("watcher")
LOCK_FILE = "/tmp/issue-fix-watcher.lock"


_shutdown_requested = False


def _handle_sigterm(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    log.info("SIGTERM received — finishing current cycle then exiting")


def main():
    parser = argparse.ArgumentParser(description="Issue Fix Agent Watcher")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log actions without executing mutations")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously with poll interval sleep (Deployment mode)")
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

    if args.loop:
        signal.signal(signal.SIGTERM, _handle_sigterm)
        log.info("Watcher starting in loop mode (poll interval: %dm)",
                 config.jira_poll_interval)
        while not _shutdown_requested:
            lock_fd = acquire_lock()
            if lock_fd is None:
                log.info("Another watcher cycle is running — skipping")
            else:
                try:
                    run_cycle(config)
                    Path("/tmp/watcher-healthy").touch()
                finally:
                    lock_fd.close()
            for _ in range(config.jira_poll_interval * 60):
                if _shutdown_requested:
                    break
                time.sleep(1)
        log.info("Watcher shutdown complete")
    else:
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
        ("Phase 2: Review dispatch", phase_review_dispatch),
        ("Phase 3: Review-fix dispatch", phase_review_fix_dispatch),
        ("Phase 4: Post-merge updates", phase_post_merge),
        ("Phase 5: Cancellation", phase_cancellation),
        ("Phase 7: Missing info re-check", phase_missing_info),
        ("Phase 8: Retry", phase_retry),
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
        f"no-autofix, bot-cancelled, bot-plan-ready, bot-proceed, bot-plan-approved) "
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
            ticket.key, "fix-investigate", prompt, config.investigate_ttl,
            model=config.fix_model,
        )
        stats.new_tickets += 1


def phase_plan_approval(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = bot-plan-ready AND (labels = bot-proceed OR labels = bot-plan-approved) "
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
            remove=["bot-plan-ready", "bot-proceed", "bot-plan-approved"],
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
            ticket.key, "fix-implement", prompt, config.implement_ttl,
            model=config.fix_model,
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


def phase_review_dispatch(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = bot-ready-for-review "
        f"AND labels NOT IN (bot-review-complete, bot-review-fix) "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql)
    log.info("Phase 2: Found %d tickets ready for review", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        active = _active_review_count(jira, config)
        if active >= config.max_concurrent_review:
            log.info("Review concurrency limit reached (%d/%d)",
                     active, config.max_concurrent_review)
            break

        if dispatcher.is_tracked(ticket.key):
            continue

        comments = jira.get_comments(ticket.key)
        pr_info = _extract_pr_info(comments)
        if not pr_info:
            log.warning("%s: Could not extract PR info from comments", ticket.key)
            continue

        jira.add_comment(
            ticket.key,
            f"## Agent Session Started\n"
            f"**Agent**: review\n"
            f"**Started**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"**Phase**: Code review",
        )

        prompt = (
            f"Review the PR for Jira ticket {ticket.key}. "
            f"Follow the issue-review skill. "
            f"Jira Site: {config.jira_site}"
        )
        dispatcher.dispatch(ticket.key, "review", prompt, config.review_ttl,
                           model=config.review_model)
        stats.reviews_dispatched += 1


def phase_review_fix_dispatch(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = bot-review-fix "
        f"AND labels NOT IN (bot-ready-for-review, bot-fix-failed) "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql)
    log.info("Phase 3: Found %d tickets needing review-fix", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        comments = jira.get_comments(ticket.key)
        cycle_count = _count_review_fix_cycles(comments)

        if cycle_count >= config.review_fix_max_cycles:
            log.info("%s: Max review-fix cycles reached (%d/%d)",
                     ticket.key, cycle_count, config.review_fix_max_cycles)
            jira.swap_labels(
                ticket.key,
                remove=["bot-review-fix"],
                add=["bot-fix-failed"],
            )
            jira.add_comment(
                ticket.key,
                f"Max review cycles ({config.review_fix_max_cycles}) exceeded "
                f"— needs human attention.\n"
                f"To retry the entire fix from scratch, add the `bot-retry` label.",
            )
            continue

        active = _active_review_fix_count(jira, config)
        if active >= config.max_concurrent_review_fix:
            log.info("Review-fix concurrency limit reached (%d/%d)",
                     active, config.max_concurrent_review_fix)
            break

        if dispatcher.is_tracked(ticket.key):
            continue

        next_cycle = cycle_count + 1
        jira.add_comment(
            ticket.key,
            f"## Agent Session Started\n"
            f"**Agent**: review-fix\n"
            f"**Started**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"**Phase**: Review-fix cycle {next_cycle}",
        )

        prompt = (
            f"Address review findings for Jira ticket {ticket.key}. "
            f"Follow the review-fix skill. This is cycle {next_cycle}. "
            f"Jira Site: {config.jira_site}"
        )
        dispatcher.dispatch(
            ticket.key, "review-fix", prompt, config.review_fix_ttl,
            model=config.review_fix_model,
        )
        stats.review_fixes_dispatched += 1


def phase_post_merge(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = f"labels = bot-review-complete AND project IN ({projects})"
    issues = jira.search(jql)
    log.info("Phase 4: Checking %d tickets for merged PRs", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        comments = jira.get_comments(ticket.key)
        pr_info = _extract_pr_info(comments)
        if not pr_info:
            log.warning("%s: No PR info found in comments", ticket.key)
            continue

        repo, pr_number = pr_info
        try:
            result = subprocess.run(
                ["gh", "pr", "view", str(pr_number), "--repo", repo,
                 "--json", "state,merged,mergedAt,mergedBy,mergeCommit"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                log.warning("%s: gh pr view failed: %s", ticket.key, result.stderr)
                continue
            pr_data = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            log.warning("%s: PR status check failed: %s", ticket.key, e)
            continue

        if pr_data.get("merged"):
            merged_by = pr_data.get("mergedBy", {}).get("login", "unknown")
            merge_commit = pr_data.get("mergeCommit", {}).get("oid", "unknown")[:12]
            jira.swap_labels(
                ticket.key,
                remove=["bot-review-complete"],
                add=["bot-merged"],
            )
            jira.add_comment(
                ticket.key,
                f"## PR Merged\n"
                f"**PR**: #{pr_number} merged\n"
                f"**Merge Commit**: {merge_commit}\n"
                f"**Merged By**: @{merged_by}\n\n"
                f"Ticket is ready for manual review and close.",
            )
            stats.merges_detected += 1

        elif pr_data.get("state") == "CLOSED":
            jira.swap_labels(
                ticket.key,
                remove=["bot-review-complete"],
                add=["bot-fix-failed"],
            )
            jira.add_comment(
                ticket.key,
                f"## PR Closed Without Merge\n"
                f"**PR**: #{pr_number} was closed without merging.\n\n"
                f"The fix was rejected or abandoned. To retry with a new "
                f"approach, add the `bot-retry` label. To opt out, add `no-autofix`.",
            )
            stats.closed_prs += 1


def phase_cancellation(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = autofix AND labels = bot-cancelled "
        f"AND labels NOT IN (bot-fix-failed, bot-merged) "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql)
    log.info("Phase 5: Found %d cancelled tickets", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        bot_labels = [l for l in ticket.labels if l.startswith("bot-")]
        remove_labels = [l for l in bot_labels if l != "bot-fix-failed"]

        jira.swap_labels(
            ticket.key,
            remove=remove_labels,
            add=["bot-fix-failed"],
        )

        has_no_autofix = "no-autofix" in ticket.labels
        if has_no_autofix:
            comment = (
                "## Pipeline Cancelled\n"
                "Cancelled by human intervention. Ticket is opted out of "
                "automation (`no-autofix` label present)."
            )
        else:
            comment = (
                "## Pipeline Cancelled\n"
                "Cancelled by human intervention (`bot-cancelled` label detected).\n"
                "Active sessions have been stopped (or will expire at TTL).\n\n"
                "To retry, add the `bot-retry` label.\n"
                "To opt out permanently, add `no-autofix`."
            )
        jira.add_comment(ticket.key, comment)
        stats.cancellations += 1


def phase_missing_info(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = autofix AND labels = bot-missing-info "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql, max_results=5)
    log.info("Phase 7: Re-checking %d missing-info tickets", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        if ticket.repo_url:
            jira.swap_labels(
                ticket.key,
                remove=["bot-missing-info"],
                add=[],
            )
            jira.add_comment(
                ticket.key,
                "Repository URL detected. Ticket re-queued for processing.",
            )
            stats.missing_info_recovered += 1
            continue

        comments = jira.get_comments(ticket.key)
        repo_from_comments = _find_repo_in_comments(comments, config)
        if repo_from_comments:
            jira.swap_labels(
                ticket.key,
                remove=["bot-missing-info"],
                add=[],
            )
            jira.add_comment(
                ticket.key,
                "Repository URL detected in comments. Ticket re-queued for processing.",
            )
            stats.missing_info_recovered += 1
            continue

        missing_info_time = _find_comment_time(comments, "## Missing Information")
        if missing_info_time:
            age_days = (datetime.utcnow() - missing_info_time).total_seconds() / 86400
            if age_days > 7:
                has_reminder = any(
                    _get_comment_body(c).startswith("Reminder:")
                    for c in comments
                )
                if not has_reminder:
                    jira.add_comment(
                        ticket.key,
                        "Reminder: This ticket is still waiting for a valid "
                        "Repository URL. Add it to the ticket description and "
                        "the bot will detect it automatically.",
                    )


def phase_retry(
    jira: JiraClient, dispatcher: Dispatcher, config: Config, stats: CycleStats
):
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = autofix AND labels = bot-fix-failed AND labels = bot-retry "
        f"AND project IN ({projects})"
    )
    issues = jira.search(jql)
    log.info("Phase 8: Found %d retry requests", len(issues))

    for issue in issues:
        ticket = jira.parse_ticket(issue)
        if ticket is None:
            continue

        comments = jira.get_comments(ticket.key)
        fail_count = sum(
            1 for c in comments
            if _get_comment_body(c).startswith("## Fix Failed")
        )
        retry_count = max(0, fail_count - 1)

        if retry_count >= config.max_fix_retries:
            log.info("%s: Max retries reached (%d/%d)",
                     ticket.key, retry_count, config.max_fix_retries)
            jira.swap_labels(ticket.key, remove=["bot-retry"], add=[])
            jira.add_comment(
                ticket.key,
                f"Maximum retries ({config.max_fix_retries}) reached. "
                f"This ticket needs human intervention. "
                f"Prior failures are documented in comments above.",
            )
            continue

        if not ticket.repo_url:
            jira.swap_labels(ticket.key, remove=["bot-retry"], add=[])
            jira.add_comment(
                ticket.key,
                "Retry failed — Repository URL is missing from the ticket.",
            )
            continue

        active = _active_fix_count(jira, config)
        if active >= config.max_concurrent_fix:
            log.info("Concurrency limit reached — deferring retry")
            break

        jira.swap_labels(
            ticket.key,
            remove=["bot-fix-failed", "bot-retry"],
            add=["bot-in-progress"],
        )
        jira.add_comment(
            ticket.key,
            f"## Agent Session Started\n"
            f"**Agent**: fix-investigate (retry {retry_count + 1})\n"
            f"**Started**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"**Phase**: Investigation (retry)",
        )

        prompt = _build_investigate_prompt(ticket, config)
        prompt += (
            f"\n\nThis is retry {retry_count + 1}. Check prior ## Fix Failed "
            f"comments on the Jira ticket for context on what was previously "
            f"attempted and why it failed. Avoid repeating the same approach."
        )
        dispatcher.dispatch(
            ticket.key, "fix-investigate", prompt, config.investigate_ttl,
            model=config.fix_model,
        )
        stats.retries_dispatched += 1


def _active_fix_count(jira: JiraClient, config: Config) -> int:
    projects = ",".join(config.watched_projects)
    jql = f"labels = bot-in-progress AND project IN ({projects})"
    return len(jira.search(jql))


def _active_review_count(jira: JiraClient, config: Config) -> int:
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = bot-ready-for-review "
        f"AND labels NOT IN (bot-review-complete, bot-review-fix, bot-fix-failed) "
        f"AND project IN ({projects})"
    )
    return len(jira.search(jql))


def _active_review_fix_count(jira: JiraClient, config: Config) -> int:
    projects = ",".join(config.watched_projects)
    jql = (
        f"labels = bot-review-fix "
        f"AND labels NOT IN (bot-ready-for-review, bot-fix-failed) "
        f"AND project IN ({projects})"
    )
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
        if ("Plan" in body or "plan" in body) and ("Branch" in body or "branch" in body):
            for pattern in [
                r"\*\*Branch\*\*:\s*`?([^\s`]+)",
                r"\*Branch\*:\s*([^\s]+)",
                r"^Branch:\s*`?([^\s`]+)",
                r"Branch\s*:\s*`?([^\s`]+)",
            ]:
                match = re.search(pattern, body, re.MULTILINE)
                if match:
                    return match.group(1)
    return None


def _extract_pr_info(comments: list[dict]) -> tuple[str, int] | None:
    for comment in reversed(comments):
        body = _get_comment_body(comment)
        if "## Fix Applied" in body:
            match = re.search(
                r"\[#(\d+)\]\(https://github\.com/([^/]+/[^/]+)/pull/\d+\)", body
            )
            if match:
                return match.group(2), int(match.group(1))
    return None


def _count_review_fix_cycles(comments: list[dict]) -> int:
    return sum(
        1 for c in comments
        if _get_comment_body(c).startswith("## Review-Fix Cycle")
    )


BOT_COMMENT_HEADERS = [
    "## Missing Information", "## Fix Applied", "## Fix Failed",
    "## Review-Fix Failed", "## Review-Fix Cycle",
    "## Agent Session Started", "## PR Merged", "## Agent Code Review",
    "## Fix Plan", "## Plan Compliance Failed", "## Audit",
    "## Pipeline Cancelled", "## PR Closed Without Merge",
    "## Plan Approval Timeout",
]


def _find_repo_in_comments(comments: list[dict], config) -> str | None:
    from .jira_client import _extract_field
    for comment in comments:
        body = _get_comment_body(comment)
        if any(body.startswith(h) for h in BOT_COMMENT_HEADERS):
            continue
        repo = _extract_field(body, "Repository")
        if repo and repo.startswith("https://"):
            from urllib.parse import urlparse
            host = urlparse(repo).hostname or ""
            if host in config.allowed_repo_hosts:
                return repo
        url_match = re.search(r"https://github\.com/[^\s)]+", body)
        if url_match:
            url = url_match.group(0)
            from urllib.parse import urlparse
            host = urlparse(url).hostname or ""
            if host in config.allowed_repo_hosts:
                return url
    return None


def _find_comment_time(comments: list[dict], header: str) -> datetime | None:
    for comment in comments:
        body = _get_comment_body(comment)
        if body.startswith(header):
            created = comment.get("created", "")
            if created:
                try:
                    return datetime.fromisoformat(
                        created.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    pass
    return None


def _get_comment_body(comment: dict) -> str:
    body = comment.get("body", "")
    if isinstance(body, dict):
        from .jira_client import adf_to_text
        return adf_to_text(body)
    return body


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
    fields = [
        ("new", stats.new_tickets),
        ("plans", stats.plans_dispatched),
        ("reviews", stats.reviews_dispatched),
        ("review_fixes", stats.review_fixes_dispatched),
        ("merges", stats.merges_detected),
        ("closed_prs", stats.closed_prs),
        ("cancellations", stats.cancellations),
        ("missing_recovered", stats.missing_info_recovered),
        ("retries", stats.retries_dispatched),
        ("stale_plans", stats.stale_plans),
        ("skipped", stats.skipped_concurrency),
        ("errors", len(stats.errors)),
    ]
    parts = [f"{k}={v}" for k, v in fields if v]
    return ", ".join(parts) if parts else "no activity"


def post_summary(config: Config, stats: CycleStats, elapsed_seconds: int):
    if not config.slack_webhook_url:
        return

    prefix = "[DRY RUN] " if config.dry_run else ""
    text = (
        f"{prefix}Issue Fix Agent — Watcher Cycle Summary ({elapsed_seconds}s)\n"
        f"• New tickets dispatched: {stats.new_tickets}\n"
        f"• Plans implemented: {stats.plans_dispatched}\n"
        f"• Reviews dispatched: {stats.reviews_dispatched}\n"
        f"• Review-fixes dispatched: {stats.review_fixes_dispatched}\n"
        f"• Retries dispatched: {stats.retries_dispatched}\n"
        f"• Merged PRs updated: {stats.merges_detected}\n"
        f"• Closed PRs detected: {stats.closed_prs}\n"
        f"• Cancelled by human: {stats.cancellations}\n"
        f"• Missing info recovered: {stats.missing_info_recovered}\n"
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
