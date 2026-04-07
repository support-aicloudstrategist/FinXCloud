"""Slack slash command parser and executor for task management.

Handles /task slash commands:
    /task create <title>       — Create a new task
    /task status [identifier]  — Show task status or list in-progress tasks
    /task assign <id> <agent>  — Reassign a task to another agent
    /task help                 — Show available commands
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a parsed and executed command."""

    text: str
    blocks: list[dict[str, Any]]
    ephemeral: bool = False


def parse_command(text: str) -> tuple[str, list[str]]:
    """Parse slash command text into action and arguments.

    Args:
        text: Raw text after the slash command (e.g. "create Fix login bug").

    Returns:
        Tuple of (action, args list).
    """
    parts = text.strip().split(None, 1)
    if not parts:
        return "help", []
    action = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    args = rest.split() if rest else []
    # Keep the full rest string available as args[0] for create
    if action == "create" and rest:
        args = [rest]
    return action, args


def handle_task_command(
    action: str,
    args: list[str],
    user_id: str,
    user_name: str,
    task_store: TaskStore | None = None,
) -> CommandResult:
    """Route a parsed command to the appropriate handler.

    Args:
        action: Command action (create, status, assign, help).
        args: Parsed arguments.
        user_id: Slack user ID of the caller.
        user_name: Slack display name.
        task_store: Backend for task CRUD (injected for testability).

    Returns:
        CommandResult with response blocks and text.
    """
    store = task_store or InMemoryTaskStore()

    handlers = {
        "create": _handle_create,
        "status": _handle_status,
        "assign": _handle_assign,
        "help": _handle_help,
    }

    handler = handlers.get(action)
    if not handler:
        return CommandResult(
            text=f"Unknown command: `{action}`. Try `/task help`.",
            blocks=_error_blocks(f"Unknown command: `{action}`", "Try `/task help` for available commands."),
        )

    return handler(args, user_id, user_name, store)


class TaskStore:
    """Abstract interface for task storage backend."""

    def create_task(self, title: str, created_by: str) -> dict[str, Any]:
        raise NotImplementedError

    def get_task(self, identifier: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def list_in_progress(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def assign_task(self, identifier: str, assignee: str) -> dict[str, Any] | None:
        raise NotImplementedError


class InMemoryTaskStore(TaskStore):
    """Simple in-memory task store for standalone usage."""

    _tasks: dict[str, dict[str, Any]] = {}
    _counter: int = 0

    def create_task(self, title: str, created_by: str) -> dict[str, Any]:
        InMemoryTaskStore._counter += 1
        identifier = f"TASK-{InMemoryTaskStore._counter}"
        task = {
            "identifier": identifier,
            "title": title,
            "status": "todo",
            "priority": "medium",
            "created_by": created_by,
            "assignee": None,
        }
        InMemoryTaskStore._tasks[identifier] = task
        return task

    def get_task(self, identifier: str) -> dict[str, Any] | None:
        return InMemoryTaskStore._tasks.get(identifier.upper())

    def list_in_progress(self) -> list[dict[str, Any]]:
        return [t for t in InMemoryTaskStore._tasks.values() if t["status"] == "in_progress"]

    def assign_task(self, identifier: str, assignee: str) -> dict[str, Any] | None:
        task = self.get_task(identifier)
        if task:
            task["assignee"] = assignee
            return task
        return None


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_create(
    args: list[str], user_id: str, user_name: str, store: TaskStore
) -> CommandResult:
    if not args:
        return CommandResult(
            text="Usage: `/task create <title>`",
            blocks=_error_blocks("Missing title", "Usage: `/task create <title>`"),
            ephemeral=True,
        )

    title = args[0]
    task = store.create_task(title=title, created_by=user_name)
    identifier = task["identifier"]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":white_check_mark: Task Created"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Task:*\n{identifier}"},
                {"type": "mrkdwn", "text": f"*Title:*\n{title}"},
                {"type": "mrkdwn", "text": f"*Status:*\ntodo"},
                {"type": "mrkdwn", "text": f"*Created by:*\n<@{user_id}>"},
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Use `/task status {identifier}` to check progress"}],
        },
    ]

    return CommandResult(
        text=f"Task {identifier} created: {title}",
        blocks=blocks,
    )


def _handle_status(
    args: list[str], user_id: str, user_name: str, store: TaskStore
) -> CommandResult:
    # Specific task lookup
    if args:
        identifier = args[0].upper()
        task = store.get_task(identifier)
        if not task:
            return CommandResult(
                text=f"Task `{identifier}` not found.",
                blocks=_error_blocks(f"Task `{identifier}` not found", "Check the identifier and try again."),
                ephemeral=True,
            )

        status_emoji = {
            "todo": ":clipboard:",
            "in_progress": ":hammer_and_wrench:",
            "done": ":white_check_mark:",
            "blocked": ":no_entry:",
        }.get(task["status"], ":grey_question:")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{status_emoji} {task['identifier']}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Title:*\n{task['title']}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{task['status']}"},
                    {"type": "mrkdwn", "text": f"*Priority:*\n{task.get('priority', 'medium')}"},
                    {"type": "mrkdwn", "text": f"*Assignee:*\n{task.get('assignee') or 'Unassigned'}"},
                ],
            },
        ]

        return CommandResult(
            text=f"{task['identifier']}: {task['title']} ({task['status']})",
            blocks=blocks,
        )

    # List in-progress tasks
    tasks = store.list_in_progress()
    if not tasks:
        return CommandResult(
            text="No tasks currently in progress.",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": ":clipboard: *No tasks currently in progress.*"},
                },
            ],
            ephemeral=True,
        )

    task_lines = [
        f"- `{t['identifier']}` — {t['title']} ({t.get('assignee') or 'unassigned'})"
        for t in tasks[:15]
    ]
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":hammer_and_wrench: In-Progress Tasks"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(task_lines)},
        },
    ]

    if len(tasks) > 15:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_Showing 15 of {len(tasks)} tasks_"}],
        })

    return CommandResult(
        text=f"{len(tasks)} tasks in progress",
        blocks=blocks,
    )


def _handle_assign(
    args: list[str], user_id: str, user_name: str, store: TaskStore
) -> CommandResult:
    if len(args) < 2:
        return CommandResult(
            text="Usage: `/task assign <identifier> <assignee>`",
            blocks=_error_blocks("Missing arguments", "Usage: `/task assign <identifier> <assignee>`"),
            ephemeral=True,
        )

    identifier = args[0].upper()
    assignee = args[1]
    # Strip @ prefix if present
    assignee = assignee.lstrip("@")

    task = store.assign_task(identifier, assignee)
    if not task:
        return CommandResult(
            text=f"Task `{identifier}` not found.",
            blocks=_error_blocks(f"Task `{identifier}` not found", "Check the identifier and try again."),
            ephemeral=True,
        )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":arrows_counterclockwise: *{identifier}* reassigned to *{assignee}*",
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Reassigned by <@{user_id}>"}],
        },
    ]

    return CommandResult(
        text=f"{identifier} assigned to {assignee}",
        blocks=blocks,
    )


def _handle_help(
    args: list[str], user_id: str, user_name: str, store: TaskStore
) -> CommandResult:
    help_text = (
        "*Available commands:*\n"
        "- `/task create <title>` — Create a new task\n"
        "- `/task status` — List all in-progress tasks\n"
        "- `/task status <identifier>` — Show details for a specific task\n"
        "- `/task assign <identifier> <assignee>` — Reassign a task\n"
        "- `/task help` — Show this help message"
    )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":book: Task Bot Commands"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": help_text},
        },
    ]

    return CommandResult(text=help_text, blocks=blocks, ephemeral=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_blocks(title: str, detail: str) -> list[dict[str, Any]]:
    """Build a simple error response in Block Kit."""
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":warning: *{title}*\n{detail}"},
        },
    ]
