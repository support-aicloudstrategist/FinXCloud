"""Schedule manager for FinXCloud — stores and evaluates instance schedules."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_SCHEDULE_PATH = os.environ.get(
    "FINXCLOUD_SCHEDULE_PATH",
    str(Path.home() / ".finxcloud" / "schedules.json"),
)


class ScheduleManager:
    """Manage start/stop schedules for EC2 instances.

    Schedules are persisted to a local JSON file.  Each schedule entry:
    {
        "id": "<uuid>",
        "instance_id": "i-abc123",
        "region": "us-east-1",
        "account_id": "123456789012",  (optional)
        "stop_time": "19:00",          (HH:MM UTC)
        "start_time": "08:00",         (HH:MM UTC)
        "days": ["mon","tue","wed","thu","fri"],
        "enabled": true,
        "created_at": "2026-04-06T...",
        "estimated_monthly_savings": 120.0  (optional)
    }
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path or _DEFAULT_SCHEDULE_PATH

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> list[dict]:
        p = Path(self._path)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Could not read schedules file at %s", self._path)
            return []

    def _save(self, schedules: list[dict]) -> None:
        p = Path(self._path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(schedules, indent=2, default=str))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_schedules(self) -> list[dict]:
        return self._load()

    def get_schedule(self, schedule_id: str) -> dict | None:
        for s in self._load():
            if s["id"] == schedule_id:
                return s
        return None

    def add_schedule(
        self,
        instance_id: str,
        region: str,
        stop_time: str,
        start_time: str,
        days: list[str] | None = None,
        account_id: str | None = None,
        estimated_monthly_savings: float = 0.0,
    ) -> dict:
        schedules = self._load()
        entry = {
            "id": str(uuid.uuid4())[:8],
            "instance_id": instance_id,
            "region": region,
            "account_id": account_id,
            "stop_time": stop_time,
            "start_time": start_time,
            "days": days or ["mon", "tue", "wed", "thu", "fri"],
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "estimated_monthly_savings": estimated_monthly_savings,
        }
        schedules.append(entry)
        self._save(schedules)
        log.info("Added schedule %s for %s", entry["id"], instance_id)
        return entry

    def update_schedule(self, schedule_id: str, **fields) -> dict | None:
        schedules = self._load()
        for s in schedules:
            if s["id"] == schedule_id:
                allowed = {
                    "stop_time", "start_time", "days", "enabled",
                    "estimated_monthly_savings",
                }
                for k, v in fields.items():
                    if k in allowed:
                        s[k] = v
                self._save(schedules)
                return s
        return None

    def delete_schedule(self, schedule_id: str) -> bool:
        schedules = self._load()
        before = len(schedules)
        schedules = [s for s in schedules if s["id"] != schedule_id]
        if len(schedules) == before:
            return False
        self._save(schedules)
        return True

    # ------------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------------

    def get_due_actions(self, now: datetime | None = None) -> list[dict]:
        """Return a list of actions that should fire at the current time.

        Each action: {"schedule_id", "instance_id", "region", "action": "stop"|"start"}
        """
        if now is None:
            now = datetime.now(timezone.utc)

        current_time = now.strftime("%H:%M")
        current_day = now.strftime("%a").lower()

        actions: list[dict] = []
        for s in self._load():
            if not s.get("enabled", True):
                continue
            if current_day not in s.get("days", []):
                continue
            if s["stop_time"] == current_time:
                actions.append({
                    "schedule_id": s["id"],
                    "instance_id": s["instance_id"],
                    "region": s["region"],
                    "action": "stop",
                })
            elif s["start_time"] == current_time:
                actions.append({
                    "schedule_id": s["id"],
                    "instance_id": s["instance_id"],
                    "region": s["region"],
                    "action": "start",
                })
        return actions

    def estimate_savings(self, hourly_cost: float, stop_time: str, start_time: str, days: list[str]) -> float:
        """Estimate monthly savings from a schedule.

        Calculates hours saved per week and multiplies by ~4.33 weeks/month.
        """
        stop_h, stop_m = map(int, stop_time.split(":"))
        start_h, start_m = map(int, start_time.split(":"))
        stop_mins = stop_h * 60 + stop_m
        start_mins = start_h * 60 + start_m

        if stop_mins >= start_mins:
            # Overnight: e.g. stop 19:00, start next day 08:00 = 13h off
            off_minutes = (24 * 60 - stop_mins) + start_mins
        else:
            # Same day: e.g. stop 08:00, start 17:00 = 9h off
            off_minutes = start_mins - stop_mins

        off_hours_per_day = off_minutes / 60
        weekly_savings = off_hours_per_day * len(days) * hourly_cost
        return round(weekly_savings * 4.33, 2)
