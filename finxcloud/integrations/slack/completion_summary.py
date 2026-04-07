"""Build enriched task completion summaries for Slack notifications.

Collects issue description, comment thread, linked commits, and duration,
then returns a data dict that the formatter can render as rich Block Kit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def enrich_completion_data(data: dict[str, Any]) -> dict[str, Any]:
    """Enrich a TASK_COMPLETED event payload with computed summary fields.

    Expects raw task data and returns an augmented copy with:
        - duration: human-readable elapsed time
        - comments_summary: condensed comment thread
        - commits_summary: formatted commit list
        - description_snippet: truncated description

    Args:
        data: Raw event payload with task details.

    Returns:
        Enriched copy of data with additional summary fields.
    """
    enriched = dict(data)

    # Duration calculation
    started_at = data.get("started_at") or data.get("created_at")
    completed_at = data.get("completed_at")
    if started_at and completed_at:
        enriched["duration"] = _format_duration(started_at, completed_at)
    elif not enriched.get("duration") and started_at:
        # Fallback: compute from start to now
        enriched["duration"] = _format_duration(started_at, datetime.now(timezone.utc).isoformat())

    # Description snippet
    desc = data.get("description", "")
    if desc and not enriched.get("description_snippet"):
        enriched["description_snippet"] = _truncate(desc, 300)

    # Comments thread summary
    comments = data.get("comments", [])
    if comments:
        enriched["comments_summary"] = _summarize_comments(comments)
        enriched["comments_count"] = len(comments)

    # Linked commits
    commits = data.get("commits", [])
    if commits:
        enriched["commits_summary"] = _format_commits(commits)
        enriched["commits_count"] = len(commits)

    # Build a combined summary if not already provided
    if not enriched.get("summary"):
        enriched["summary"] = _build_auto_summary(enriched)

    return enriched


def _format_duration(start_iso: str, end_iso: str) -> str:
    """Compute human-readable duration between two ISO timestamps."""
    try:
        start = _parse_iso(start_iso)
        end = _parse_iso(end_iso)
        delta = end - start
        total_seconds = int(delta.total_seconds())

        if total_seconds < 0:
            return "instant"

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")

        return " ".join(parts) if parts else "<1m"
    except (ValueError, TypeError):
        return "unknown"


def _parse_iso(value: str | datetime) -> datetime:
    """Parse an ISO datetime string or return a datetime as-is."""
    if isinstance(value, datetime):
        return value
    # Handle Z suffix and fractional seconds
    s = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rsplit(" ", 1)[0] + "..."


def _summarize_comments(comments: list[dict[str, Any]]) -> str:
    """Build a condensed summary of the comment thread.

    Shows the last few comments with author attribution.
    """
    MAX_COMMENTS = 5
    recent = comments[-MAX_COMMENTS:]
    lines = []
    for c in recent:
        author = c.get("author") or c.get("authorAgentId") or "unknown"
        body = _truncate(c.get("body", ""), 150)
        lines.append(f"- *{author}:* {body}")

    if len(comments) > MAX_COMMENTS:
        lines.insert(0, f"_({len(comments)} total comments, showing last {MAX_COMMENTS})_")

    return "\n".join(lines)


def _format_commits(commits: list[dict[str, Any]]) -> str:
    """Format linked commits as a bullet list."""
    lines = []
    for commit in commits[:10]:
        sha = commit.get("sha", commit.get("id", ""))[:7]
        message = _truncate(commit.get("message", ""), 80)
        author = commit.get("author", "")
        prefix = f"`{sha}`" if sha else "-"
        suffix = f" ({author})" if author else ""
        lines.append(f"{prefix} {message}{suffix}")

    if len(commits) > 10:
        lines.append(f"_...and {len(commits) - 10} more commits_")

    return "\n".join(lines)


def _build_auto_summary(data: dict[str, Any]) -> str:
    """Build an automatic summary from available enriched fields."""
    parts = []

    title = data.get("title", "")
    if title:
        parts.append(f"Completed: *{title}*")

    if data.get("description_snippet"):
        parts.append(data["description_snippet"])

    if data.get("duration"):
        parts.append(f"Duration: {data['duration']}")

    if data.get("commits_count"):
        parts.append(f"{data['commits_count']} commit(s) linked")

    if data.get("comments_count"):
        parts.append(f"{data['comments_count']} comment(s) in thread")

    return "\n".join(parts) if parts else "Task completed."
