"""Slack Block Kit message formatters for Paperclip task lifecycle events.

Each formatter builds a list of Slack blocks for a specific event type,
using Block Kit components (header, section, fields, context, divider).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from finxcloud.integrations.events import EventType


# Status emoji mapping for visual clarity
_STATUS_EMOJI = {
    "created": ":new:",
    "completed": ":white_check_mark:",
    "blocked": ":no_entry:",
    "approval_requested": ":raised_hand:",
    "approval_resolved": ":thumbsup:",
}

_EVENT_TITLES = {
    EventType.TASK_CREATED: "Task Created",
    EventType.TASK_COMPLETED: "Task Completed",
    EventType.TASK_BLOCKED: "Task Blocked",
    EventType.APPROVAL_REQUESTED: "Approval Requested",
    EventType.APPROVAL_RESOLVED: "Approval Resolved",
}


def format_event(event_type: EventType, data: dict[str, Any]) -> tuple[list[dict], str]:
    """Format a task event into Slack Block Kit blocks and fallback text.

    Args:
        event_type: The lifecycle event type.
        data: Event payload with task/approval details.

    Returns:
        Tuple of (blocks list, fallback text string).
    """
    formatter = _FORMATTERS.get(event_type, _format_generic)
    return formatter(event_type, data)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _task_fields(data: dict[str, Any]) -> list[dict]:
    """Build common task info fields."""
    fields = []
    if data.get("identifier"):
        fields.append({"type": "mrkdwn", "text": f"*Task:*\n{data['identifier']}"})
    if data.get("title"):
        fields.append({"type": "mrkdwn", "text": f"*Title:*\n{data['title']}"})
    if data.get("priority"):
        fields.append({"type": "mrkdwn", "text": f"*Priority:*\n{data['priority'].title()}"})
    if data.get("assignee"):
        fields.append({"type": "mrkdwn", "text": f"*Assignee:*\n{data['assignee']}"})
    if data.get("project"):
        fields.append({"type": "mrkdwn", "text": f"*Project:*\n{data['project']}"})
    return fields


def _format_task_created(event_type: EventType, data: dict[str, Any]) -> tuple[list[dict], str]:
    title = data.get("title", "Untitled")
    identifier = data.get("identifier", "")
    fallback = f":new: Task created: {identifier} — {title}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{_STATUS_EMOJI['created']} Task Created"},
        },
        {"type": "section", "fields": _task_fields(data)},
    ]

    if data.get("description"):
        desc = data["description"][:300]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Description:*\n{desc}"},
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_FinXCloud | {_timestamp()}_"}],
    })

    return blocks, fallback


def _format_task_completed(event_type: EventType, data: dict[str, Any]) -> tuple[list[dict], str]:
    from finxcloud.integrations.slack.completion_summary import enrich_completion_data

    enriched = enrich_completion_data(data)
    title = enriched.get("title", "Untitled")
    identifier = enriched.get("identifier", "")
    fallback = f":white_check_mark: Task completed: {identifier} — {title}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{_STATUS_EMOJI['completed']} Task Completed"},
        },
        {"type": "section", "fields": _task_fields(enriched)},
    ]

    # Duration bar
    if enriched.get("duration"):
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f":clock1: Completed in *{enriched['duration']}*"},
            ],
        })

    # Description snippet
    if enriched.get("description_snippet"):
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Description:*\n{enriched['description_snippet']}",
            },
        })

    # Auto-generated or provided summary
    if enriched.get("summary"):
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:*\n{enriched['summary']}"},
        })

    # Comment thread (expandable section)
    if enriched.get("comments_summary"):
        blocks.append({"type": "divider"})
        comments_header = f":speech_balloon: *Comment Thread* ({enriched.get('comments_count', 0)} comments)"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": comments_header},
        })
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": enriched["comments_summary"][:3000],
            },
        })

    # Linked commits
    if enriched.get("commits_summary"):
        blocks.append({"type": "divider"})
        commits_header = f":git: *Linked Commits* ({enriched.get('commits_count', 0)} commits)"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": commits_header},
        })
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": enriched["commits_summary"][:3000],
            },
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_FinXCloud | {_timestamp()}_"}],
    })

    return blocks, fallback


def _format_task_blocked(event_type: EventType, data: dict[str, Any]) -> tuple[list[dict], str]:
    title = data.get("title", "Untitled")
    identifier = data.get("identifier", "")
    reason = data.get("blocker_reason", "No reason provided")
    fallback = f":no_entry: Task blocked: {identifier} — {title}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{_STATUS_EMOJI['blocked']} Task Blocked"},
        },
        {"type": "section", "fields": _task_fields(data)},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Blocker:*\n{reason}"},
        },
    ]

    if data.get("blocked_by"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Needs action from:*\n{data['blocked_by']}"},
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_FinXCloud | {_timestamp()}_"}],
    })

    return blocks, fallback


def _format_approval_requested(
    event_type: EventType, data: dict[str, Any]
) -> tuple[list[dict], str]:
    title = data.get("title", "Approval needed")
    identifier = data.get("identifier", "")
    fallback = f":raised_hand: Approval requested: {identifier} — {title}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{_STATUS_EMOJI['approval_requested']} Approval Requested",
            },
        },
        {"type": "section", "fields": _task_fields(data)},
    ]

    if data.get("approval_type"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Type:*\n{data['approval_type']}"},
        })

    if data.get("requested_by"):
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Requested by: {data['requested_by']}"},
            ],
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_FinXCloud | {_timestamp()}_"}],
    })

    return blocks, fallback


def _format_approval_resolved(
    event_type: EventType, data: dict[str, Any]
) -> tuple[list[dict], str]:
    title = data.get("title", "Approval resolved")
    identifier = data.get("identifier", "")
    resolution = data.get("resolution", "approved")
    fallback = f":thumbsup: Approval {resolution}: {identifier} — {title}"

    emoji = ":white_check_mark:" if resolution == "approved" else ":x:"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Approval {resolution.title()}",
            },
        },
        {"type": "section", "fields": _task_fields(data)},
    ]

    if data.get("resolved_by"):
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Resolved by: {data['resolved_by']}"},
            ],
        })

    if data.get("resolution_note"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Note:*\n{data['resolution_note']}"},
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_FinXCloud | {_timestamp()}_"}],
    })

    return blocks, fallback


def _format_generic(event_type: EventType, data: dict[str, Any]) -> tuple[list[dict], str]:
    """Fallback formatter for unknown event types."""
    title = _EVENT_TITLES.get(event_type, event_type.value.replace("_", " ").title())
    fallback = f"FinXCloud: {title}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"FinXCloud: {title}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{str(data)[:500]}```"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_FinXCloud | {_timestamp()}_"}],
        },
    ]

    return blocks, fallback


_FORMATTERS = {
    EventType.TASK_CREATED: _format_task_created,
    EventType.TASK_COMPLETED: _format_task_completed,
    EventType.TASK_BLOCKED: _format_task_blocked,
    EventType.APPROVAL_REQUESTED: _format_approval_requested,
    EventType.APPROVAL_RESOLVED: _format_approval_resolved,
}
