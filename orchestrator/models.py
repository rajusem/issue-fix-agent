from dataclasses import dataclass, field


@dataclass
class Ticket:
    key: str
    summary: str
    labels: list[str]
    repo_url: str | None = None
    branch: str | None = None
    commit: str | None = None
    skill_urls: list[str] = field(default_factory=list)
    knowledge_repo: str | None = None


@dataclass
class DispatchRecord:
    pid: int
    agent: str
    started_at: str
    ttl_minutes: int
    log_file: str


@dataclass
class CycleStats:
    new_tickets: int = 0
    plans_dispatched: int = 0
    reviews_dispatched: int = 0
    review_fixes_dispatched: int = 0
    merges_detected: int = 0
    closed_prs: int = 0
    cancellations: int = 0
    missing_info_recovered: int = 0
    retries_dispatched: int = 0
    stale_plans: int = 0
    skipped_concurrency: int = 0
    errors: list[str] = field(default_factory=list)
