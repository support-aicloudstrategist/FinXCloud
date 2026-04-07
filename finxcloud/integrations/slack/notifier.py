"""Slack notifier service — bridges the event dispatcher to Slack.

Registers as a handler on the EventDispatcher and sends formatted
Block Kit messages to a configured Slack channel via the SlackClient.
"""

from __future__ import annotations

import logging
from typing import Any

from finxcloud.integrations.events import Event, EventDispatcher, EventType, get_dispatcher
from finxcloud.integrations.slack.client import SlackClient
from finxcloud.integrations.slack.formatters import format_event

log = logging.getLogger(__name__)


class SlackNotifier:
    """Connects the event bus to Slack message delivery.

    Usage:
        notifier = SlackNotifier()          # reads env vars
        notifier.register()                 # hooks into global dispatcher
        # ... events are now auto-forwarded to Slack

    Or with explicit dependencies:
        client = SlackClient(bot_token="xoxb-...", channel_id="C01234")
        dispatcher = EventDispatcher()
        notifier = SlackNotifier(client=client, dispatcher=dispatcher)
        notifier.register()
    """

    def __init__(
        self,
        client: SlackClient | None = None,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self.client = client or SlackClient()
        self.dispatcher = dispatcher or get_dispatcher()

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

    def handle_event(self, event: Event) -> None:
        """Handle an event by formatting and sending it to Slack.

        For TASK_COMPLETED events, also sends a DM to the task creator
        if a creator_channel is provided in the event data.
        """
        if not self.client.is_configured:
            log.debug("Slack not configured — skipping event %s", event.type.value)
            return

        blocks, fallback_text = format_event(event.type, event.data)

        # Post to the main channel
        result = self.client.post_message(blocks=blocks, text=fallback_text)

        if result.get("ok"):
            log.info("Slack notification sent for %s", event.type.value)
        else:
            log.error(
                "Slack notification failed for %s: %s",
                event.type.value,
                result.get("error", "unknown"),
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
        """Send a notification directly without going through the dispatcher.

        Useful for one-off messages or testing.
        """
        blocks, fallback_text = format_event(event_type, data)
        return self.client.post_message(blocks=blocks, text=fallback_text, channel=channel)


def setup_slack_notifications(
    dispatcher: EventDispatcher | None = None,
) -> SlackNotifier:
    """Convenience: create a SlackNotifier and register it on the dispatcher.

    Call this once at application startup to enable Slack notifications
    for all task lifecycle events.
    """
    notifier = SlackNotifier(dispatcher=dispatcher)
    notifier.register()
    return notifier
