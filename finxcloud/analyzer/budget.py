"""Budget tracking and forecasting for FinXCloud.

Allows setting monthly budgets per account and forecasts month-end
spend based on linear extrapolation of daily cost trends.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from finxcloud.analyzer.cost_explorer import CostExplorerAnalyzer

log = logging.getLogger(__name__)

_DEFAULT_BUDGET_PATH = Path.home() / ".finxcloud" / "budgets.json"


class BudgetTracker:
    """Track monthly budgets and forecast month-end spend."""

    def __init__(
        self,
        cost_explorer: CostExplorerAnalyzer,
        budget_path: Path | str | None = None,
    ) -> None:
        self.ce = cost_explorer
        self._budget_path = Path(budget_path) if budget_path else _DEFAULT_BUDGET_PATH

    def get_budgets(self) -> dict[str, float]:
        """Load saved budgets from disk. Returns {account_id: monthly_budget}."""
        if not self._budget_path.exists():
            return {}
        try:
            return json.loads(self._budget_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Failed to read budgets from %s", self._budget_path)
            return {}

    def set_budget(self, account_id: str, monthly_budget: float) -> None:
        """Save a monthly budget for the given account."""
        budgets = self.get_budgets()
        budgets[account_id] = monthly_budget
        self._budget_path.parent.mkdir(parents=True, exist_ok=True)
        self._budget_path.write_text(
            json.dumps(budgets, indent=2), encoding="utf-8",
        )
        log.info("Budget set for %s: $%.2f/mo", account_id, monthly_budget)

    def analyze(self, account_id: str = "default", days: int = 30) -> dict:
        """Compute budget vs actual vs forecast for the current month.

        Returns:
            Dict with keys: account_id, budget, actual_mtd, forecast_eom,
            days_elapsed, days_in_month, daily_avg, on_track, pct_used.
        """
        today = date.today()
        first_of_month = today.replace(day=1)
        days_elapsed = (today - first_of_month).days + 1

        # Days in this month
        if today.month == 12:
            next_month_first = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month_first = today.replace(month=today.month + 1, day=1)
        days_in_month = (next_month_first - first_of_month).days

        # Get cost data for current month so far
        daily_costs = self.ce.get_daily_costs(days_elapsed)
        actual_mtd = sum(d["amount"] for d in daily_costs)

        # Linear extrapolation
        daily_avg = actual_mtd / max(days_elapsed, 1)
        forecast_eom = daily_avg * days_in_month

        # Budget lookup
        budgets = self.get_budgets()
        budget = budgets.get(account_id, 0.0)

        on_track = forecast_eom <= budget if budget > 0 else True
        pct_used = (actual_mtd / budget * 100) if budget > 0 else 0.0

        return {
            "account_id": account_id,
            "budget": round(budget, 2),
            "actual_mtd": round(actual_mtd, 2),
            "forecast_eom": round(forecast_eom, 2),
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
            "daily_avg": round(daily_avg, 2),
            "on_track": on_track,
            "pct_used": round(pct_used, 1),
        }
