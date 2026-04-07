"""Paperclip API client implementing the TaskStore interface.

Replaces the in-memory TaskStore with real Paperclip REST API calls
so that Slack slash commands operate on live task data.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from finxcloud.integrations.slack.commands import TaskStore

log = logging.getLogger(__name__)


class PaperclipClient(TaskStore):
    """TaskStore backed by the Paperclip REST API.

    Configuration via environment variables:
        PAPERCLIP_API_URL   - Base URL of the Paperclip API (e.g. http://localhost:3000)
        PAPERCLIP_API_KEY   - Bearer token for authentication
        PAPERCLIP_COMPANY_ID - Company ID for issue operations
        SLACK_PAPERCLIP_USER_MAP - JSON mapping of Slack user IDs to Paperclip agent IDs
                                   e.g. {"U12345": "agent-uuid-1", "U67890": "agent-uuid-2"}
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        company_id: str | None = None,
        user_map: dict[str, str] | None = None,
    ) -> None:
        self.api_url = (api_url or os.environ.get("PAPERCLIP_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("PAPERCLIP_API_KEY", "")
        self.company_id = company_id or os.environ.get("PAPERCLIP_COMPANY_ID", "")
        self.user_map = user_map or _load_user_map()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url and self.api_key and self.company_id)

    # ---- TaskStore interface ------------------------------------------------

    def create_task(self, title: str, created_by: str) -> dict[str, Any]:
        """Create an issue in Paperclip and return a normalised task dict."""
        payload: dict[str, Any] = {
            "title": title,
            "status": "todo",
            "priority": "medium",
        }
        # Map Slack user to Paperclip agent if possible
        agent_id = self.user_map.get(created_by)
        if agent_id:
            payload["assigneeAgentId"] = agent_id

        data = self._api_call(
            "POST",
            f"/api/companies/{self.company_id}/issues",
            payload,
        )
        return _normalise_issue(data)

    def get_task(self, identifier: str) -> dict[str, Any] | None:
        """Fetch a single issue by its identifier (e.g. AIC-41)."""
        # Search by identifier via the query endpoint
        results = self._api_call(
            "GET",
            f"/api/companies/{self.company_id}/issues?q={identifier}",
        )
        if not isinstance(results, list):
            results = results.get("items", results.get("data", []))

        for issue in results:
            if issue.get("identifier", "").upper() == identifier.upper():
                return _normalise_issue(issue)
        return None

    def list_in_progress(self) -> list[dict[str, Any]]:
        """List all in-progress issues for the company."""
        results = self._api_call(
            "GET",
            f"/api/companies/{self.company_id}/issues?status=in_progress",
        )
        if not isinstance(results, list):
            results = results.get("items", results.get("data", []))

        return [_normalise_issue(i) for i in results]

    def assign_task(self, identifier: str, assignee: str) -> dict[str, Any] | None:
        """Reassign an issue to a different agent."""
        task = self.get_task(identifier)
        if not task:
            return None

        issue_id = task.get("id")
        if not issue_id:
            return None

        # Resolve assignee: could be a Slack user ID, agent name, or agent UUID
        agent_id = self.user_map.get(assignee) or self._resolve_agent_id(assignee)
        if not agent_id:
            log.warning("Could not resolve assignee %r to a Paperclip agent", assignee)
            return None

        data = self._api_call(
            "PATCH",
            f"/api/issues/{issue_id}",
            {"assigneeAgentId": agent_id},
        )
        return _normalise_issue(data)

    # ---- Extended methods (beyond TaskStore) ---------------------------------

    def list_agents(self) -> list[dict[str, Any]]:
        """List all agents in the company."""
        return self._api_call("GET", f"/api/companies/{self.company_id}/agents") or []

    def get_issue_comments(self, issue_id: str) -> list[dict[str, Any]]:
        """Get comments for an issue."""
        return self._api_call("GET", f"/api/issues/{issue_id}/comments") or []

    def add_comment(self, issue_id: str, body: str) -> dict[str, Any]:
        """Add a comment to an issue."""
        return self._api_call("POST", f"/api/issues/{issue_id}/comments", {"body": body})

    def get_agent(self, name_or_id: str) -> dict[str, Any] | None:
        """Look up an agent by name, urlKey, or UUID."""
        agents = self.list_agents()
        if not isinstance(agents, list):
            return None
        for agent in agents:
            if agent.get("id") == name_or_id:
                return agent
            if agent.get("urlKey", "").lower() == name_or_id.lower():
                return agent
            if agent.get("name", "").lower() == name_or_id.lower():
                return agent
        return None

    def get_agent_runs(self, agent_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get recent heartbeat runs for an agent."""
        data = self._api_call(
            "GET",
            f"/api/companies/{self.company_id}/agents/{agent_id}/runs?limit={limit}",
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("data", []))
        return []

    def wake_agent(self, agent_id: str) -> dict[str, Any]:
        """Trigger a heartbeat run for an agent."""
        return self._api_call(
            "POST",
            f"/api/companies/{self.company_id}/agents/{agent_id}/wake",
            {},
        )

    # ---- HTTP plumbing ------------------------------------------------------

    def _api_call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated request to the Paperclip API."""
        url = f"{self.api_url}{path}"

        body = json.dumps(payload).encode("utf-8") if payload else None
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self.api_key}",
            },
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            resp_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            log.error("Paperclip API %s %s -> %d: %s", method, path, exc.code, resp_body)
            return {}
        except Exception as exc:
            log.error("Paperclip API call failed: %s %s -> %s", method, path, exc)
            return {}

    def _resolve_agent_id(self, name_or_id: str) -> str | None:
        """Try to resolve an agent name or URL key to an agent UUID."""
        agents = self.list_agents()
        if not isinstance(agents, list):
            return None
        for agent in agents:
            if agent.get("id") == name_or_id:
                return name_or_id
            if agent.get("urlKey") == name_or_id.lower():
                return agent["id"]
            if agent.get("name", "").lower() == name_or_id.lower():
                return agent["id"]
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_issue(data: dict[str, Any]) -> dict[str, Any]:
    """Convert a Paperclip issue response to the flat dict the commands expect."""
    if not data:
        return {}
    return {
        "id": data.get("id", ""),
        "identifier": data.get("identifier", ""),
        "title": data.get("title", ""),
        "status": data.get("status", "todo"),
        "priority": data.get("priority", "medium"),
        "created_by": data.get("createdByAgentId") or data.get("createdByUserId") or "",
        "assignee": data.get("assigneeAgentId") or data.get("assigneeUserId") or None,
    }


def _load_user_map() -> dict[str, str]:
    """Load Slack user -> Paperclip agent ID mapping from env."""
    raw = os.environ.get("SLACK_PAPERCLIP_USER_MAP", "")
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
        if isinstance(mapping, dict):
            return mapping
    except json.JSONDecodeError:
        log.warning("SLACK_PAPERCLIP_USER_MAP is not valid JSON — ignoring")
    return {}
