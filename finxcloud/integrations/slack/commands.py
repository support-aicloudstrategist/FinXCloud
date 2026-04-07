"""Slack slash command parser and executor for task and agent management.

Handles /task slash commands:
    /task create <title>       — Create a new task
    /task status [identifier]  — Show task status or list in-progress tasks
    /task assign <id> <agent>  — Reassign a task to another agent
    /task help                 — Show available commands

Handles /agent slash commands:
    /agent list                — List all company agents with status
    /agent status <name>       — Show agent details, current task, budget
    /agent wake <name>         — Trigger a heartbeat run
    /agent runs <name>         — Show recent runs
    /agent help                — Show available agent commands
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


# ---------------------------------------------------------------------------
# Agent commands (/agent list, /agent status, /agent wake, /agent runs)
# ---------------------------------------------------------------------------

def handle_agent_command(
    action: str,
    args: list[str],
    user_id: str,
    user_name: str,
    paperclip_client: Any | None = None,
) -> CommandResult:
    """Route a parsed /agent command to the appropriate handler."""
    if paperclip_client is None:
        return CommandResult(
            text="Agent commands require a Paperclip connection.",
            blocks=_error_blocks(
                "Not configured",
                "Paperclip API is not configured. Agent commands are unavailable.",
            ),
        )

    handlers = {
        "list": _handle_agent_list,
        "status": _handle_agent_status,
        "wake": _handle_agent_wake,
        "runs": _handle_agent_runs,
        "help": _handle_agent_help,
    }

    handler = handlers.get(action)
    if not handler:
        return CommandResult(
            text=f"Unknown agent command: `{action}`. Try `/agent help`.",
            blocks=_error_blocks(
                f"Unknown command: `{action}`",
                "Try `/agent help` for available commands.",
            ),
        )

    return handler(args, user_id, user_name, paperclip_client)


def _handle_agent_list(
    args: list[str], user_id: str, user_name: str, client: Any
) -> CommandResult:
    """List all company agents with status."""
    agents = client.list_agents()
    if not agents:
        return CommandResult(
            text="No agents found.",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": ":robot_face: *No agents found in this company.*"},
            }],
            ephemeral=True,
        )

    status_emoji = {
        "running": ":large_green_circle:",
        "idle": ":white_circle:",
        "paused": ":double_vertical_bar:",
    }

    lines = []
    for a in agents:
        name = a.get("name", "Unknown")
        s = a.get("status", "idle")
        emoji = status_emoji.get(s, ":grey_question:")
        role = a.get("role", "")
        lines.append(f"{emoji} *{name}* — {role} ({s})")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":robot_face: Company Agents"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines[:20])},
        },
    ]

    if len(agents) > 20:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_Showing 20 of {len(agents)} agents_"}],
        })

    return CommandResult(
        text=f"{len(agents)} agents",
        blocks=blocks,
    )


def _handle_agent_status(
    args: list[str], user_id: str, user_name: str, client: Any
) -> CommandResult:
    """Show detailed status for a specific agent."""
    if not args:
        return CommandResult(
            text="Usage: `/agent status <name>`",
            blocks=_error_blocks("Missing agent name", "Usage: `/agent status <name>`"),
            ephemeral=True,
        )

    name = args[0]
    agent = client.get_agent(name)
    if not agent:
        return CommandResult(
            text=f"Agent `{name}` not found.",
            blocks=_error_blocks(f"Agent `{name}` not found", "Check the name and try again. Use `/agent list` to see all agents."),
            ephemeral=True,
        )

    status_emoji = {
        "running": ":large_green_circle:",
        "idle": ":white_circle:",
        "paused": ":double_vertical_bar:",
    }

    a_status = agent.get("status", "idle")
    emoji = status_emoji.get(a_status, ":grey_question:")
    a_name = agent.get("name", "Unknown")
    a_role = agent.get("role", "")
    a_title = agent.get("title", "") or a_role
    budget_monthly = agent.get("budgetMonthlyCents", 0)
    spent_monthly = agent.get("spentMonthlyCents", 0)
    pause_reason = agent.get("pauseReason") or "—"
    last_heartbeat = agent.get("lastHeartbeatAt") or "Never"

    budget_str = f"${budget_monthly / 100:.2f}" if budget_monthly else "Unlimited"
    spent_str = f"${spent_monthly / 100:.2f}"

    fields = [
        {"type": "mrkdwn", "text": f"*Name:*\n{a_name}"},
        {"type": "mrkdwn", "text": f"*Status:*\n{emoji} {a_status}"},
        {"type": "mrkdwn", "text": f"*Role:*\n{a_title}"},
        {"type": "mrkdwn", "text": f"*Budget:*\n{spent_str} / {budget_str}"},
    ]

    if a_status == "paused":
        fields.append({"type": "mrkdwn", "text": f"*Pause reason:*\n{pause_reason}"})

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {a_name}"},
        },
        {
            "type": "section",
            "fields": fields,
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Last heartbeat: {last_heartbeat}"}],
        },
    ]

    return CommandResult(
        text=f"{a_name}: {a_status}",
        blocks=blocks,
    )


def _handle_agent_wake(
    args: list[str], user_id: str, user_name: str, client: Any
) -> CommandResult:
    """Trigger a heartbeat run for an agent."""
    if not args:
        return CommandResult(
            text="Usage: `/agent wake <name>`",
            blocks=_error_blocks("Missing agent name", "Usage: `/agent wake <name>`"),
            ephemeral=True,
        )

    name = args[0]
    agent = client.get_agent(name)
    if not agent:
        return CommandResult(
            text=f"Agent `{name}` not found.",
            blocks=_error_blocks(f"Agent `{name}` not found", "Use `/agent list` to see all agents."),
            ephemeral=True,
        )

    agent_id = agent["id"]
    a_name = agent.get("name", name)
    result = client.wake_agent(agent_id)

    if not result or result.get("error"):
        err = result.get("error", "Unknown error") if result else "No response"
        return CommandResult(
            text=f"Failed to wake {a_name}: {err}",
            blocks=_error_blocks(f"Failed to wake {a_name}", str(err)),
        )

    run_id = result.get("runId") or result.get("id") or "—"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":zap: *Heartbeat triggered for {a_name}*\nRun ID: `{run_id}`",
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Triggered by <@{user_id}>"}],
        },
    ]

    return CommandResult(
        text=f"Heartbeat triggered for {a_name} (run {run_id})",
        blocks=blocks,
    )


def _handle_agent_runs(
    args: list[str], user_id: str, user_name: str, client: Any
) -> CommandResult:
    """Show recent runs for an agent."""
    if not args:
        return CommandResult(
            text="Usage: `/agent runs <name>`",
            blocks=_error_blocks("Missing agent name", "Usage: `/agent runs <name>`"),
            ephemeral=True,
        )

    name = args[0]
    agent = client.get_agent(name)
    if not agent:
        return CommandResult(
            text=f"Agent `{name}` not found.",
            blocks=_error_blocks(f"Agent `{name}` not found", "Use `/agent list` to see all agents."),
            ephemeral=True,
        )

    agent_id = agent["id"]
    a_name = agent.get("name", name)
    runs = client.get_agent_runs(agent_id, limit=5)

    if not runs:
        return CommandResult(
            text=f"No recent runs for {a_name}.",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":clipboard: *No recent runs for {a_name}.*"},
            }],
            ephemeral=True,
        )

    status_emoji = {
        "running": ":large_green_circle:",
        "completed": ":white_check_mark:",
        "queued": ":hourglass_flowing_sand:",
        "failed": ":x:",
        "cancelled": ":no_entry:",
    }

    lines = []
    for r in runs[:5]:
        r_id = r.get("id", "—")[:8]
        r_status = r.get("status", "unknown")
        emoji = status_emoji.get(r_status, ":grey_question:")
        started = r.get("startedAt") or "—"
        source = r.get("invocationSource") or "—"
        lines.append(f"{emoji} `{r_id}` — {r_status} | {source} | {started}")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":gear: Recent Runs — {a_name}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
    ]

    return CommandResult(
        text=f"{len(runs)} recent runs for {a_name}",
        blocks=blocks,
    )


def _handle_agent_help(
    args: list[str], user_id: str, user_name: str, client: Any
) -> CommandResult:
    """Show available agent commands."""
    help_text = (
        "*Available agent commands:*\n"
        "- `/agent list` — List all company agents with status\n"
        "- `/agent status <name>` — Show agent details, current task, budget\n"
        "- `/agent wake <name>` — Trigger a heartbeat run\n"
        "- `/agent runs <name>` — Show recent runs for an agent\n"
        "- `/agent help` — Show this help message"
    )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":robot_face: Agent Bot Commands"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": help_text},
        },
    ]

    return CommandResult(text=help_text, blocks=blocks, ephemeral=True)
