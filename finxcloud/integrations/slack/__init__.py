"""Slack integration for FinXCloud — bot notifications, commands, and Block Kit messages."""

from finxcloud.integrations.slack.bot import SlackBot
from finxcloud.integrations.slack.client import SlackClient
from finxcloud.integrations.slack.commands import CommandResult, handle_task_command, parse_command
from finxcloud.integrations.slack.formatters import format_event
from finxcloud.integrations.slack.notifier import SlackNotifier

__all__ = [
    "SlackBot",
    "SlackClient",
    "SlackNotifier",
    "CommandResult",
    "format_event",
    "handle_task_command",
    "parse_command",
]
