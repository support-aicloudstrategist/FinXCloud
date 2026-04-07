"""Paperclip event poller — polls the Paperclip API for real-time events.

Periodically fetches issues, agent runs, and approvals from the Paperclip
API, detects state changes since the last poll, and emits events through
the EventDispatcher for downstream notification handlers (e.g. Slack).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from finxcloud.integrations.events import Event, EventDispatcher, EventType, get_dispatcher
from finxcloud.integrations.slack.paperclip_client import PaperclipClient

log = logging.getLogger(__name__)

# Default polling interval in seconds
DEFAULT_POLL_INTERVAL = 30


class PaperclipEventPoller:
    """Polls the Paperclip API and emits events when state changes are detected.

    Tracks the last-known state of issues, agent runs, and approvals.
    On each poll cycle, compares current state to detect:
      - New issues created
      - Issue status changes (including completions and blocks)
      - Agent runs started or completed
      - New pending approvals

    Usage:
        client = PaperclipClient()
        poller = PaperclipEventPoller(client)
        poller.start()   # runs in a background thread
        # ... later ...
        poller.stop()
    """

    def __init__(
        self,
        client: PaperclipClient | None = None,
        dispatcher: EventDispatcher | None = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self.client = client or PaperclipClient()
        self.dispatcher = dispatcher or get_dispatcher()
        self.poll_interval = poll_interval

        # State tracking
        self._known_issues: dict[str, dict[str, Any]] = {}
        self._known_runs: dict[str, dict[str, Any]] = {}
        self._known_approvals: set[str] = set()

        # Thread control
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_configured(self) -> bool:
        return self.client.is_configured

    def start(self) -> None:
        """Start polling in a background daemon thread."""
        if not self.is_configured:
            log.warning("PaperclipClient not configured — poller will not start")
            return
        if self._thread and self._thread.is_alive():
            log.warning("Poller already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="paperclip-poller")
        self._thread.start()
        log.info("PaperclipEventPoller started (interval=%ds)", self.poll_interval)

    def stop(self) -> None:
        """Signal the poller to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.poll_interval + 5)
        log.info("PaperclipEventPoller stopped")

    def poll_once(self) -> list[Event]:
        """Run a single poll cycle and return the events emitted.

        Useful for testing or manual one-shot polling.
        """
        events: list[Event] = []
        events.extend(self._poll_issues())
        events.extend(self._poll_agent_runs())
        events.extend(self._poll_approvals())
        return events

    # ---- Internal polling loop ------------------------------------------------

    def _poll_loop(self) -> None:
        """Background polling loop."""
        # Seed initial state without emitting events
        self._seed_state()

        while not self._stop_event.is_set():
            try:
                emitted = self.poll_once()
                if emitted:
                    log.info("Poll cycle emitted %d event(s)", len(emitted))
            except Exception:
                log.exception("Error during poll cycle")

            self._stop_event.wait(timeout=self.poll_interval)

    def _seed_state(self) -> None:
        """Load current state without emitting events (initial baseline)."""
        try:
            issues = self.client.list_issues(status="todo,in_progress,blocked,in_review,done", limit=100)
            for issue in issues:
                issue_id = issue.get("id", "")
                if issue_id:
                    self._known_issues[issue_id] = issue

            agents = self.client.list_agents()
            if isinstance(agents, list):
                for agent in agents:
                    agent_id = agent.get("id", "")
                    if agent_id:
                        runs = self.client.get_agent_runs(agent_id, limit=3)
                        for run in runs:
                            run_id = run.get("id", "")
                            if run_id:
                                self._known_runs[run_id] = run

            approvals = self.client.list_approvals(status="pending")
            for approval in approvals:
                approval_id = approval.get("id", "")
                if approval_id:
                    self._known_approvals.add(approval_id)

            log.info(
                "Poller seeded: %d issues, %d runs, %d approvals",
                len(self._known_issues),
                len(self._known_runs),
                len(self._known_approvals),
            )
        except Exception:
            log.exception("Error seeding poller state")

    # ---- Issue polling --------------------------------------------------------

    def _poll_issues(self) -> list[Event]:
        """Check for new issues and status changes."""
        events: list[Event] = []
        try:
            current_issues = self.client.list_issues(
                status="todo,in_progress,blocked,in_review,done", limit=100,
            )
        except Exception:
            log.exception("Failed to poll issues")
            return events

        current_by_id: dict[str, dict[str, Any]] = {}
        for issue in current_issues:
            issue_id = issue.get("id", "")
            if not issue_id:
                continue
            current_by_id[issue_id] = issue

            prev = self._known_issues.get(issue_id)
            if prev is None:
                # New issue
                event = Event(type=EventType.TASK_CREATED, data=issue)
                self.dispatcher.dispatch(event)
                events.append(event)
            elif prev.get("status") != issue.get("status"):
                # Status changed
                old_status = prev.get("status", "unknown")
                new_status = issue.get("status", "unknown")

                event_data = {
                    **issue,
                    "old_status": old_status,
                    "new_status": new_status,
                }

                if new_status == "done":
                    event = Event(type=EventType.TASK_COMPLETED, data=event_data)
                elif new_status == "blocked":
                    event = Event(type=EventType.TASK_BLOCKED, data=event_data)
                else:
                    event = Event(type=EventType.ISSUE_STATUS_CHANGED, data=event_data)

                self.dispatcher.dispatch(event)
                events.append(event)

        self._known_issues = current_by_id
        return events

    # ---- Agent run polling ----------------------------------------------------

    def _poll_agent_runs(self) -> list[Event]:
        """Check for new or completed agent runs."""
        events: list[Event] = []
        try:
            agents = self.client.list_agents()
            if not isinstance(agents, list):
                return events
        except Exception:
            log.exception("Failed to poll agents")
            return events

        for agent in agents:
            agent_id = agent.get("id", "")
            agent_name = agent.get("name", "Unknown")
            if not agent_id:
                continue

            try:
                runs = self.client.get_agent_runs(agent_id, limit=5)
            except Exception:
                log.debug("Failed to get runs for agent %s", agent_name)
                continue

            for run in runs:
                run_id = run.get("id", "")
                if not run_id:
                    continue

                run_data = {
                    **run,
                    "agent_name": agent_name,
                    "agent_id": agent_id,
                }

                prev = self._known_runs.get(run_id)
                if prev is None:
                    # New run
                    if run.get("status") == "running":
                        event = Event(type=EventType.AGENT_RUN_STARTED, data=run_data)
                        self.dispatcher.dispatch(event)
                        events.append(event)
                elif prev.get("status") == "running" and run.get("status") != "running":
                    # Run completed
                    event = Event(type=EventType.AGENT_RUN_COMPLETED, data=run_data)
                    self.dispatcher.dispatch(event)
                    events.append(event)

                self._known_runs[run_id] = run

        return events

    # ---- Approval polling -----------------------------------------------------

    def _poll_approvals(self) -> list[Event]:
        """Check for new pending approvals."""
        events: list[Event] = []
        try:
            pending = self.client.list_approvals(status="pending")
        except Exception:
            log.exception("Failed to poll approvals")
            return events

        for approval in pending:
            approval_id = approval.get("id", "")
            if approval_id and approval_id not in self._known_approvals:
                self._known_approvals.add(approval_id)
                event = Event(
                    type=EventType.APPROVAL_REQUESTED,
                    data={
                        "approval_id": approval_id,
                        "title": approval.get("title", "Approval needed"),
                        "approval_type": approval.get("type", ""),
                        "requested_by": approval.get("requestedByAgentId", ""),
                        **approval,
                    },
                )
                self.dispatcher.dispatch(event)
                events.append(event)

        # Also check resolved approvals to emit APPROVAL_RESOLVED
        try:
            resolved = self.client.list_approvals(status="approved,rejected")
        except Exception:
            return events

        for approval in resolved:
            approval_id = approval.get("id", "")
            if approval_id and approval_id in self._known_approvals:
                self._known_approvals.discard(approval_id)
                event = Event(
                    type=EventType.APPROVAL_RESOLVED,
                    data={
                        "approval_id": approval_id,
                        "title": approval.get("title", "Approval resolved"),
                        "resolution": approval.get("status", "approved"),
                        **approval,
                    },
                )
                self.dispatcher.dispatch(event)
                events.append(event)

        return events
