"""Event dispatcher for FinXCloud integrations.

Provides a simple pub/sub event bus that routes task lifecycle events
to registered messaging providers (Slack, Telegram, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)


class EventType(str, Enum):
    """Supported task lifecycle events."""

    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"


@dataclass
class Event:
    """An event emitted by the task management system."""

    type: EventType
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


class EventHandler(Protocol):
    """Protocol for event handler callables."""

    def __call__(self, event: Event) -> None: ...


class EventDispatcher:
    """Registry and dispatcher for event handlers.

    Usage:
        dispatcher = EventDispatcher()
        dispatcher.register(EventType.TASK_CREATED, my_handler)
        dispatcher.dispatch(Event(type=EventType.TASK_CREATED, data={...}))
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Callable[[Event], None]]] = {}

    def register(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)
        log.debug("Registered handler %s for %s", handler.__name__, event_type.value)

    def register_all(self, handler: Callable[[Event], None]) -> None:
        """Register a handler for all event types."""
        for event_type in EventType:
            self.register(event_type, handler)

    def unregister(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """Remove a handler for a specific event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def dispatch(self, event: Event) -> list[dict[str, Any]]:
        """Dispatch an event to all registered handlers.

        Returns a list of results (success/error dicts) for each handler.
        """
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            log.info("No handlers registered for event %s", event.type.value)
            return []

        results: list[dict[str, Any]] = []
        for handler in handlers:
            try:
                handler(event)
                results.append({"handler": handler.__name__, "status": "ok"})
            except Exception as exc:
                log.error(
                    "Handler %s failed for event %s: %s",
                    handler.__name__,
                    event.type.value,
                    exc,
                )
                results.append({
                    "handler": handler.__name__,
                    "status": "error",
                    "error": str(exc),
                })
        return results


# Module-level singleton for convenience
_default_dispatcher: EventDispatcher | None = None


def get_dispatcher() -> EventDispatcher:
    """Get or create the default global event dispatcher."""
    global _default_dispatcher
    if _default_dispatcher is None:
        _default_dispatcher = EventDispatcher()
    return _default_dispatcher


def emit(event_type: EventType, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Convenience function: emit an event on the default dispatcher."""
    event = Event(type=event_type, data=data)
    return get_dispatcher().dispatch(event)
