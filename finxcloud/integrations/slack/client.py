"""Slack API client for FinXCloud bot notifications.

Uses the Slack Web API (chat.postMessage) with a bot token.
No external SDK dependency — uses stdlib urllib only.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

log = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackClient:
    """Lightweight Slack Web API client using bot token auth.

    Configuration via environment variables:
        SLACK_BOT_TOKEN     — Bot User OAuth Token (xoxb-...)
        SLACK_CHANNEL_ID    — Default channel to post to
        SLACK_SIGNING_SECRET — For verifying incoming requests (future use)
    """

    def __init__(
        self,
        bot_token: str | None = None,
        channel_id: str | None = None,
        signing_secret: str | None = None,
    ) -> None:
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN", "")
        self.channel_id = channel_id or os.environ.get("SLACK_CHANNEL_ID", "")
        self.signing_secret = signing_secret or os.environ.get("SLACK_SIGNING_SECRET", "")

    @property
    def is_configured(self) -> bool:
        """Check if the client has the minimum config to send messages."""
        return bool(self.bot_token and self.channel_id)

    def post_message(
        self,
        blocks: list[dict[str, Any]],
        text: str = "",
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Post a Block Kit message to a Slack channel.

        Args:
            blocks: Slack Block Kit block array.
            text: Fallback plain text (shown in notifications).
            channel: Override the default channel ID.

        Returns:
            Slack API response dict.
        """
        target_channel = channel or self.channel_id
        if not self.bot_token:
            log.warning("SLACK_BOT_TOKEN not set — skipping message")
            return {"ok": False, "error": "not_configured", "detail": "SLACK_BOT_TOKEN missing"}
        if not target_channel:
            log.warning("SLACK_CHANNEL_ID not set — skipping message")
            return {"ok": False, "error": "not_configured", "detail": "SLACK_CHANNEL_ID missing"}

        payload = {
            "channel": target_channel,
            "blocks": blocks,
            "text": text or "FinXCloud notification",
        }

        return self._api_call("chat.postMessage", payload)

    def _api_call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Make an authenticated call to the Slack Web API."""
        url = f"{SLACK_API_BASE}/{method}"
        body = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self.bot_token}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            if not result.get("ok"):
                log.error("Slack API error: %s", result.get("error", "unknown"))
            else:
                log.info("Slack message sent to %s", payload.get("channel"))

            return result
        except urllib.error.HTTPError as exc:
            log.error("Slack HTTP error: %d %s", exc.code, exc.reason)
            return {"ok": False, "error": f"http_{exc.code}", "detail": exc.reason}
        except Exception as exc:
            log.error("Slack API call failed: %s", exc)
            return {"ok": False, "error": "request_failed", "detail": str(exc)}
