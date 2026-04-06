"""Webhook and Slack notification sender for FinXCloud."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = os.environ.get(
    "FINXCLOUD_WEBHOOK_CONFIG_PATH",
    str(Path.home() / ".finxcloud" / "webhooks.json"),
)


class WebhookConfig:
    """Manage webhook URL configuration stored in a local JSON file.

    Config format:
    {
        "webhooks": [
            {
                "id": "abc123",
                "name": "Slack #cloud-costs",
                "url": "https://hooks.slack.com/services/...",
                "type": "slack",
                "enabled": true,
                "events": ["scan_complete", "anomaly_detected", "budget_threshold"]
            }
        ]
    }
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path or _DEFAULT_CONFIG_PATH

    def _load(self) -> dict:
        p = Path(self._path)
        if not p.exists():
            return {"webhooks": []}
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {"webhooks": []}

    def _save(self, data: dict) -> None:
        p = Path(self._path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))

    def list_webhooks(self) -> list[dict]:
        return self._load().get("webhooks", [])

    def add_webhook(
        self,
        url: str,
        name: str = "",
        webhook_type: str = "generic",
        events: list[str] | None = None,
    ) -> dict:
        import uuid
        data = self._load()
        entry = {
            "id": str(uuid.uuid4())[:8],
            "name": name or ("Slack" if "slack" in url.lower() else "Webhook"),
            "url": url,
            "type": webhook_type if webhook_type != "generic" else (
                "slack" if "hooks.slack.com" in url else "generic"
            ),
            "enabled": True,
            "events": events or ["scan_complete", "anomaly_detected", "budget_threshold"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data.setdefault("webhooks", []).append(entry)
        self._save(data)
        return entry

    def update_webhook(self, webhook_id: str, **fields) -> dict | None:
        data = self._load()
        for wh in data.get("webhooks", []):
            if wh["id"] == webhook_id:
                allowed = {"name", "url", "type", "enabled", "events"}
                for k, v in fields.items():
                    if k in allowed:
                        wh[k] = v
                self._save(data)
                return wh
        return None

    def delete_webhook(self, webhook_id: str) -> bool:
        data = self._load()
        before = len(data.get("webhooks", []))
        data["webhooks"] = [w for w in data.get("webhooks", []) if w["id"] != webhook_id]
        if len(data["webhooks"]) == before:
            return False
        self._save(data)
        return True

    def get_webhooks_for_event(self, event: str) -> list[dict]:
        return [
            w for w in self.list_webhooks()
            if w.get("enabled", True) and event in w.get("events", [])
        ]


class NotificationSender:
    """Send notifications via webhooks (generic HTTP POST or Slack Block Kit)."""

    def __init__(self, config: WebhookConfig | None = None) -> None:
        self.config = config or WebhookConfig()

    def notify(self, event: str, data: dict) -> list[dict]:
        """Send a notification for the given event to all matching webhooks.

        Returns a list of send results.
        """
        webhooks = self.config.get_webhooks_for_event(event)
        results: list[dict] = []
        for wh in webhooks:
            result = self._send(wh, event, data)
            results.append(result)
        return results

    def send_to_url(self, url: str, event: str, data: dict) -> dict:
        """Send directly to a URL without using stored config."""
        wh_type = "slack" if "hooks.slack.com" in url else "generic"
        return self._send({"url": url, "type": wh_type, "name": "direct"}, event, data)

    def _send(self, webhook: dict, event: str, data: dict) -> dict:
        url = webhook["url"]
        wh_type = webhook.get("type", "generic")

        if wh_type == "slack":
            payload = self._build_slack_payload(event, data)
        else:
            payload = self._build_generic_payload(event, data)

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
            log.info("Webhook %s sent to %s — status %d", event, webhook.get("name", url), status)
            return {"webhook": webhook.get("name", url), "status": "ok", "http_status": status}
        except urllib.error.HTTPError as e:
            log.error("Webhook HTTP error for %s: %d %s", url, e.code, e.reason)
            return {"webhook": webhook.get("name", url), "status": "error", "error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            log.error("Webhook send failed for %s: %s", url, e)
            return {"webhook": webhook.get("name", url), "status": "error", "error": str(e)}

    def _build_slack_payload(self, event: str, data: dict) -> dict:
        """Build a Slack Block Kit message for the event."""
        event_labels = {
            "scan_complete": "Scan Complete",
            "anomaly_detected": "Cost Anomaly Detected",
            "budget_threshold": "Budget Threshold Crossed",
        }
        title = event_labels.get(event, event.replace("_", " ").title())
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"FinXCloud: {title}"},
            },
        ]

        fields: list[dict] = []
        if event == "scan_complete":
            overview = data.get("overview", {})
            fields = [
                {"type": "mrkdwn", "text": f"*Total Resources:*\n{overview.get('total_resources', 'N/A')}"},
                {"type": "mrkdwn", "text": f"*30-Day Cost:*\n${overview.get('total_cost_30d', 0):.2f}"},
                {"type": "mrkdwn", "text": f"*Potential Savings:*\n${overview.get('total_potential_savings', 0):.2f}"},
                {"type": "mrkdwn", "text": f"*Savings %:*\n{overview.get('savings_percentage', 0):.1f}%"},
            ]
        elif event == "anomaly_detected":
            anomaly = data.get("anomaly", {})
            fields = [
                {"type": "mrkdwn", "text": f"*Date:*\n{anomaly.get('date', 'N/A')}"},
                {"type": "mrkdwn", "text": f"*Amount:*\n${anomaly.get('amount', 0):.2f}"},
                {"type": "mrkdwn", "text": f"*Rolling Avg:*\n${anomaly.get('rolling_avg', 0):.2f}"},
                {"type": "mrkdwn", "text": f"*Above Avg:*\n{anomaly.get('pct_above_avg', 0):.1f}%"},
            ]
        elif event == "budget_threshold":
            fields = [
                {"type": "mrkdwn", "text": f"*Budget:*\n${data.get('budget', 0):.2f}/mo"},
                {"type": "mrkdwn", "text": f"*MTD Spend:*\n${data.get('actual_mtd', 0):.2f}"},
                {"type": "mrkdwn", "text": f"*Forecast EOM:*\n${data.get('forecast_eom', 0):.2f}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{'Over Budget' if not data.get('on_track') else 'On Track'}"},
            ]

        if fields:
            blocks.append({"type": "section", "fields": fields})

        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_FinXCloud | {timestamp}_"}],
        })

        return {"blocks": blocks}

    def _build_generic_payload(self, event: str, data: dict) -> dict:
        """Build a generic JSON webhook payload."""
        return {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "finxcloud",
            "data": data,
        }
