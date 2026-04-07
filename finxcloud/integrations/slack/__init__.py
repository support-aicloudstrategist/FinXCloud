"""Slack integration for FinXCloud — bot notifications and Block Kit messages."""

from finxcloud.integrations.slack.client import SlackClient
from finxcloud.integrations.slack.formatters import format_event
from finxcloud.integrations.slack.notifier import SlackNotifier

__all__ = ["SlackClient", "SlackNotifier", "format_event"]
