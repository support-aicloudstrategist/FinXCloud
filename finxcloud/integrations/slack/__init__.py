"""Slack integration for FinXCloud — bot notifications, commands, and Block Kit messages."""

from finxcloud.integrations.slack.bot import SlackBot
from finxcloud.integrations.slack.client import SlackClient
from finxcloud.integrations.slack.commands import (
    CommandResult,
    handle_agent_command,
    handle_task_command,
    handle_ticket_command,
    parse_command,
    parse_ticket_command,
)
from finxcloud.integrations.slack.formatters import format_event
from finxcloud.integrations.slack.notifier import SlackNotifier, setup_slack_notifications
from finxcloud.integrations.slack.paperclip_client import PaperclipClient
from finxcloud.integrations.slack.poller import PaperclipEventPoller

__all__ = [
    "SlackBot",
    "SlackClient",
    "SlackNotifier",
    "PaperclipClient",
    "PaperclipEventPoller",
    "CommandResult",
    "format_event",
    "handle_agent_command",
    "handle_task_command",
    "handle_ticket_command",
    "parse_command",
    "parse_ticket_command",
    "setup_slack_notifications",
]
