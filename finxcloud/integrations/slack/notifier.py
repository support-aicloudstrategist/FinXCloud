"""Slack notifier service — bridges Paperclip events to Slack.

Supports two modes:
  1. Local event bus (legacy) — registers on the EventDispatcher
  2. Paperclip poller (real-time) — polls the Paperclip API for changes

Includes channel routing so different event types can target different
Slack channels, and DM support for approval notifications.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from finxcloud.integrations.events import Event, EventDispatcher, EventType, get_dispatcher
from finxcloud.integrations.slack.client import SlackClient
from finxcloud.integrations.slack.formatters import format_event

log = logging.getLogger(__name__)

# Default channel routing: event type -> channel override
# Configured via SLACK_CHANNEL_ROUTING env var as JSON, e.g.:
# {"agent_run_started": "C_OPS_CHANNEL", "task_created": "C_TASKS_CHANNEL"}
_DEFAULT_ROUTING: dict[str, str] = {}


def _load_channel_routing() -> dict[str, str]:
    """Load channel routing config from SLACK_CHANNEL_ROUTING env var."""
    raw = os.environ.get("SLACK_CHANNEL_ROUTING", "")
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
        if isinstance(mapping, dict):
            return mapping
    except json.JSONDecodeError:
        log.warning("SLACK_CHANNEL_ROUTING is not valid JSON — using defaults")
    return {}


def _load_approval_dm_channel() -> str:
    """Load the board user DM channel for approval notifications."""
    return os.environ.get("SLACK_APPROVAL_DM_CHANNEL", "")


class SlackNotifier:
    """Connects Paperclip events to Slack message delivery.

    Supports channel routing so agent events go to #ops,
    task events go to #tasks, and approvals DM the board user.

    Usage (with poller):
        from finxcloud.integrations.slack.poller import PaperclipEventPoller

        notifier = SlackNotifier()
        notifier.register()          # hooks into event dispatcher
        poller = PaperclipEventPoller()
        poller.start()               # polls Paperclip, emits events -> notifier handles them

    Channel routing config (env var SLACK_CHANNEL_ROUTING):
        {
            "agent_run_started": "C0OPS123",
            "agent_run_completed": "C0OPS123",
            "task_created": "C0TASKS456",
            "task_completed": "C0TASKS456",
            "issue_status_changed": "C0TASKS456",
            "task_blocked": "C0TASKS456",
            "approval_requested": "C0APPROVALS789",
            "approval_resolved": "C0APPROVALS789"
        }
    """

    def __init__(
        self,
        client: SlackClient | None = None,
        dispatcher: EventDispatcher | None = None,
        channel_routing: dict[str, str] | None = None,
        approval_dm_channel: str | None = None,
    ) -> None:
        self.client = client or SlackClient()
        self.dispatcher = dispatcher or get_dispatcher()
        self.channel_routing = channel_routing if channel_routing is not None else _load_channel_routing()
        self.approval_dm_channel = approval_dm_channel or _load_approval_dm_channel()

    def register(self, event_types: list[EventType] | None = None) -> None:
        """Register this notifier as a handler on the event dispatcher.

        Args:
            event_types: Specific events to listen for. Defaults to all.
        """
        if not self.client.is_configured:
            log.warning(
                "Slack client not configured (missing SLACK_BOT_TOKEN or SLACK_CHANNEL_ID). "
                "Notifier registered but messages will be skipped."
            )

        if event_types:
            for et in event_types:
                self.dispatcher.register(et, self.handle_event)
        else:
            self.dispatcher.register_all(self.handle_event)

        log.info("SlackNotifier registered for %s",
                 "all events" if not event_types else [e.value for e in event_types])

    def _resolve_channel(self, event_type: EventType) -> str | None:
        """Resolve the target channel for an event type.

        Returns the routed channel, or None to use the client default.
        """
        return self.channel_routing.get(event_type.value)

    def handle_event(self, event: Event) -> None:
        """Handle an event by formatting and sending it to the appropriate Slack channel."""
        if not self.client.is_configured:
            log.debug("Slack not configured — skipping event %s", event.type.value)
            return

        blocks, fallback_text = format_event(event.type, event.data)

        # Determine target channel via routing config
        target_channel = self._resolve_channel(event.type)

        # Post to the routed (or default) channel
        result = self.client.post_message(
            blocks=blocks, text=fallback_text, channel=target_channel,
        )

        if result.get("ok"):
            log.info("Slack notification sent for %s -> %s",
                     event.type.value, target_channel or "default")
        else:
            log.error(
                "Slack notification failed for %s: %s",
                event.type.value,
                result.get("error", "unknown"),
            )

        # DM board user for approval requests
        if event.type == EventType.APPROVAL_REQUESTED and self.approval_dm_channel:
            dm_result = self.client.post_message(
                blocks=blocks,
                text=fallback_text,
                channel=self.approval_dm_channel,
            )
            if dm_result.get("ok"):
                log.info("Approval DM sent to %s", self.approval_dm_channel)
            else:
                log.debug(
                    "Approval DM failed for %s: %s",
                    self.approval_dm_channel,
                    dm_result.get("error", "unknown"),
                )

        # For completions, also DM the task creator if channel is provided
        if (
            event.type == EventType.TASK_COMPLETED
            and event.data.get("creator_channel")
        ):
            dm_result = self.client.post_message(
                blocks=blocks,
                text=fallback_text,
                channel=event.data["creator_channel"],
            )
            if dm_result.get("ok"):
                log.info("Completion DM sent to creator channel %s", event.data["creator_channel"])
            else:
                log.debug(
                    "Completion DM failed for %s: %s",
                    event.data["creator_channel"],
                    dm_result.get("error", "unknown"),
                )

    def send_direct(
        self,
        event_type: EventType,
        data: dict[str, Any],
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Send a notification directly without going through the dispatcher."""
        blocks, fallback_text = format_event(event_type, data)
        return self.client.post_message(blocks=blocks, text=fallback_text, channel=channel)


def setup_slack_notifications(
    dispatcher: EventDispatcher | None = None,
    enable_poller: bool = False,
    poll_interval: int = 30,
) -> SlackNotifier:
    """Create a SlackNotifier and optionally start the Paperclip event poller.

    Args:
        dispatcher: Optional event dispatcher override.
        enable_poller: If True, start polling Paperclip API for real events.
        poll_interval: Polling interval in seconds (default 30).

    Returns:
        The configured SlackNotifier instance.
    """
    notifier = SlackNotifier(dispatcher=dispatcher)
    notifier.register()

    if enable_poller:
        from finxcloud.integrations.slack.poller import PaperclipEventPoller

        poller = PaperclipEventPoller(
            dispatcher=notifier.dispatcher,
            poll_interval=poll_interval,
        )
        poller.start()
        log.info("Paperclip event poller started with %ds interval", poll_interval)

    return notifier
