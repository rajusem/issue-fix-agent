import logging
import re
import time
from fnmatch import fnmatch
from urllib.parse import urlparse

from atlassian import Jira

from .config import Config
from .models import Ticket

log = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, config: Config):
        self.jira = Jira(
            url=f"https://{config.jira_site}",
            username=config.jira_username,
            password=config.jira_api_token,
        )
        self.config = config

    def search(self, jql: str, max_results: int = 50) -> list[dict]:
        url = "rest/api/3/search/jql"
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,labels,description,comment",
        }
        result = self.jira.get(url, params=params)
        issues = result.get("issues", [])
        for issue in issues:
            if "key" not in issue:
                issue["key"] = issue.get("id", "")
        return issues

    def get_issue(self, key: str) -> dict:
        return self.jira.issue(key)

    def get_comments(self, key: str) -> list[dict]:
        data = self.jira.issue_get_comments(key)
        return data.get("comments", [])

    def add_comment(self, key: str, body: str) -> None:
        if self.config.dry_run:
            log.info("[DRY RUN] Would add comment to %s: %s...", key, body[:80])
            return
        self.jira.issue_add_comment(key, body)

    def swap_labels(self, key: str, remove: list[str], add: list[str]) -> None:
        if self.config.dry_run:
            log.info("[DRY RUN] %s: remove %s, add %s", key, remove, add)
            return
        update_ops = []
        for label in remove:
            update_ops.append({"remove": label})
        for label in add:
            update_ops.append({"add": label})
        self.jira.put(
            f"rest/api/3/issue/{key}",
            data={"update": {"labels": update_ops}},
        )
        self._verify_labels(key, expected=add, absent=remove)

    def get_labels(self, key: str) -> list[str]:
        issue = self.jira.issue(key, fields="labels")
        return issue.get("fields", {}).get("labels", [])

    def _verify_labels(self, key: str, expected: list[str], absent: list[str]) -> None:
        labels = self.get_labels(key)
        if self._labels_ok(labels, expected, absent):
            return
        time.sleep(2)
        labels = self.get_labels(key)
        if not self._labels_ok(labels, expected, absent):
            raise RuntimeError(
                f"Label swap failed on {key}: "
                f"expected {expected}, absent {absent}, got {labels}"
            )

    @staticmethod
    def _labels_ok(labels: list[str], expected: list[str], absent: list[str]) -> bool:
        return (
            all(l in labels for l in expected)
            and all(l not in labels for l in absent)
        )

    def parse_ticket(self, issue: dict) -> Ticket | None:
        fields = issue.get("fields", {})
        key = issue.get("key", "")
        summary = fields.get("summary", "")
        labels = fields.get("labels", [])

        desc_raw = fields.get("description", "")
        if isinstance(desc_raw, dict):
            desc = adf_to_text(desc_raw)
        elif isinstance(desc_raw, str):
            desc = desc_raw
        else:
            desc = ""

        repo_url = _extract_field(desc, "Repository")
        branch = _extract_field(desc, "Branch")
        commit = _extract_field(desc, "Commit")
        knowledge_repo = _extract_field(desc, "Knowledge Repo")

        skill_urls = _extract_skill_urls(desc)

        if repo_url:
            repo_url = self._validate_repo_url(repo_url, key)

        if skill_urls:
            skill_urls = [
                u for u in skill_urls
                if self._validate_skill_url(u, key)
            ]

        return Ticket(
            key=key,
            summary=summary,
            labels=labels,
            repo_url=repo_url,
            branch=branch,
            commit=commit,
            skill_urls=skill_urls,
            knowledge_repo=knowledge_repo,
        )

    def _validate_repo_url(self, url: str, ticket_key: str) -> str | None:
        if not url.startswith("https://"):
            log.warning("%s: repo URL rejected — not HTTPS: %s", ticket_key, url)
            return None
        parsed = urlparse(url)
        if "@" in (parsed.netloc or ""):
            log.warning("%s: repo URL rejected — embedded credentials", ticket_key)
            return None
        if ".." in (parsed.path or ""):
            log.warning("%s: repo URL rejected — path traversal", ticket_key)
            return None
        host = parsed.hostname or ""
        if host not in self.config.allowed_repo_hosts:
            log.warning("%s: repo host %s not in allowed list", ticket_key, host)
            return None
        return url

    def _validate_skill_url(self, url: str, ticket_key: str) -> bool:
        if not url.startswith("https://"):
            return False
        for pattern in self.config.skill_url_allowlist:
            if fnmatch(url, pattern):
                return True
        log.warning("%s: skill URL not on allowlist: %s", ticket_key, url)
        return False


def adf_to_text(node: dict) -> str:
    try:
        if not isinstance(node, dict):
            return ""
        node_type = node.get("type", "")
        if node_type == "text":
            return node.get("text", "")
        children = node.get("content", [])
        parts = [adf_to_text(c) for c in children if isinstance(c, dict)]
        text = "".join(parts)
        if node_type in ("paragraph", "heading", "listItem", "blockquote"):
            return text + "\n"
        if node_type == "hardBreak":
            return "\n"
        if node_type == "rule":
            return "\n---\n"
        return text
    except (TypeError, AttributeError):
        return ""


def _extract_field(text: str, field_name: str) -> str | None:
    escaped = re.escape(field_name)
    for pattern in [
        rf"\*\*{escaped}\*\*\s*:\s*(.+)",
        rf"\*{escaped}\*\s*:\s*(.+)",
        rf"^{escaped}\s*:\s*(.+)",
    ]:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def _extract_skill_urls(text: str) -> list[str]:
    urls = []
    in_skills = False
    for line in text.splitlines():
        if re.match(r"\*\*Skills?\*\*\s*:", line):
            in_skills = True
            url_on_line = re.search(r"https://\S+", line)
            if url_on_line:
                urls.append(url_on_line.group(0))
            continue
        if in_skills:
            if line.strip().startswith("- ") or line.strip().startswith("* "):
                url_match = re.search(r"https://\S+", line)
                if url_match:
                    urls.append(url_match.group(0))
            elif line.strip().startswith("**"):
                break
            elif line.strip() == "":
                continue
            else:
                break
    return urls[:5]
