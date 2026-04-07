"""Slack bot handler for incoming events, slash commands, and DMs.

Provides request signature verification, event routing, and
integration with the command parser for task management via Slack.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qs

from finxcloud.integrations.slack.client import SlackClient
from finxcloud.integrations.slack.commands import (
    CommandResult,
    TaskStore,
    handle_task_command,
    parse_command,
)

log = logging.getLogger(__name__)


class SlackBot:
    """Handles incoming Slack interactions: slash commands, events, and DMs.

    Configuration:
        Requires a SlackClient instance and optionally a TaskStore backend.
        Request verification uses SLACK_SIGNING_SECRET from the client.
    """

    def __init__(
        self,
        client: SlackClient | None = None,
        task_store: TaskStore | None = None,
    ) -> None:
        self.client = client or SlackClient()
        self.task_store = task_store

    def verify_request(
        self,
        body: bytes,
        timestamp: str,
        signature: str,
    ) -> bool:
        """Verify that a request came from Slack using the signing secret.

        Args:
            body: Raw request body bytes.
            timestamp: X-Slack-Request-Timestamp header value.
            signature: X-Slack-Signature header value.

        Returns:
            True if the signature is valid.
        """
        if not self.client.signing_secret:
            log.warning("SLACK_SIGNING_SECRET not set — skipping verification")
            return True

        # Reject requests older than 5 minutes to prevent replay attacks
        try:
            if abs(time.time() - float(timestamp)) > 300:
                log.warning("Slack request timestamp too old: %s", timestamp)
                return False
        except (ValueError, TypeError):
            return False

        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        computed = (
            "v0="
            + hmac.new(
                self.client.signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )

        return hmac.compare_digest(computed, signature)

    def handle_slash_command(self, form_data: dict[str, str]) -> dict[str, Any]:
        """Process a Slack slash command payload.

        Args:
            form_data: Parsed form body from Slack (command, text, user_id, etc.).

        Returns:
            Slack response dict (response_type + blocks/text).
        """
        command = form_data.get("command", "")
        text = form_data.get("text", "")
        user_id = form_data.get("user_id", "")
        user_name = form_data.get("user_name", "unknown")

        log.info("Slash command from %s: %s %s", user_name, command, text)

        action, args = parse_command(text)
        result = handle_task_command(
            action=action,
            args=args,
            user_id=user_id,
            user_name=user_name,
            task_store=self.task_store,
        )

        response_type = "ephemeral" if result.ephemeral else "in_channel"
        return {
            "response_type": response_type,
            "text": result.text,
            "blocks": result.blocks,
        }

    def handle_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process a Slack Events API payload.

        Handles:
            - url_verification challenge
            - message events (DMs parsed as task instructions)
            - app_mention events

        Args:
            payload: Parsed JSON body from Slack Events API.

        Returns:
            Response dict (may contain challenge or acknowledgement).
        """
        # URL verification handshake
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}

        event = payload.get("event", {})
        event_type = event.get("type", "")

        # Ignore bot messages to prevent loops
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return {"ok": True}

        if event_type == "message":
            return self._handle_message_event(event)
        elif event_type == "app_mention":
            return self._handle_mention_event(event)

        log.debug("Unhandled event type: %s", event_type)
        return {"ok": True}

    def _handle_message_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle a direct message to the bot.

        Parses the message text as a task command if it looks like one,
        otherwise responds with a help hint.
        """
        text = event.get("text", "").strip()
        channel = event.get("channel", "")
        user_id = event.get("user", "")

        if not text or not channel:
            return {"ok": True}

        # Check if it looks like a task command (starts with "task" or known action)
        action, args, is_command = _extract_command_from_message(text)

        if is_command:
            result = handle_task_command(
                action=action,
                args=args,
                user_id=user_id,
                user_name=user_id,
                task_store=self.task_store,
            )
            self.client.post_message(
                blocks=result.blocks,
                text=result.text,
                channel=channel,
            )
        else:
            # Treat unrecognized DMs as a task creation request
            result = handle_task_command(
                action="create",
                args=[text],
                user_id=user_id,
                user_name=user_id,
                task_store=self.task_store,
            )
            self.client.post_message(
                blocks=result.blocks,
                text=result.text,
                channel=channel,
            )

        return {"ok": True}

    def _handle_mention_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle an @mention of the bot in a channel.

        Strips the bot mention and processes the remaining text as a command.
        """
        text = event.get("text", "")
        channel = event.get("channel", "")
        user_id = event.get("user", "")

        # Strip bot mention (<@BOT_ID>)
        import re
        cleaned = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

        if not cleaned:
            # Just a mention with no text — respond with help
            result = handle_task_command(
                action="help", args=[], user_id=user_id, user_name=user_id,
                task_store=self.task_store,
            )
        else:
            action, args, _ = _extract_command_from_message(cleaned)
            result = handle_task_command(
                action=action, args=args, user_id=user_id, user_name=user_id,
                task_store=self.task_store,
            )

        self.client.post_message(
            blocks=result.blocks,
            text=result.text,
            channel=channel,
        )
        return {"ok": True}


def _extract_command_from_message(text: str) -> tuple[str, list[str], bool]:
    """Try to extract a task command from free-form message text.

    Recognizes patterns like:
        "task create Fix the bug"
        "create Fix the bug"
        "status TASK-5"
        "assign TASK-5 @alice"

    Returns:
        Tuple of (action, args, is_recognized_command).
    """
    lower = text.lower().strip()

    # Strip leading "task" keyword if present
    if lower.startswith("task "):
        text = text[5:].strip()
        lower = lower[5:].strip()

    known_actions = {"create", "status", "assign", "help"}
    first_word = lower.split()[0] if lower.split() else ""

    if first_word in known_actions:
        action, args = parse_command(text)
        return action, args, True

    return "create", [text], False


def parse_slash_form_body(body: bytes) -> dict[str, str]:
    """Parse a URL-encoded Slack slash command body into a flat dict.

    Args:
        body: Raw request body bytes.

    Returns:
        Dict with string keys and first-value strings.
    """
    parsed = parse_qs(body.decode("utf-8"))
    return {k: v[0] for k, v in parsed.items()}
