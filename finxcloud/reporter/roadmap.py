"""Implementation roadmap report generator for FinXCloud AWS cost optimization."""

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Phase definitions: (phase_number, label, effort_level, timeline)
_PHASE_DEFS: list[tuple[int, str, str, str]] = [
    (1, "Quick Wins", "low", "< 1 day per item"),
    (2, "Medium Term", "medium", "1-2 weeks"),
    (3, "Strategic", "high", "1+ month"),
]


class RoadmapReporter:
    """Generates a phased implementation roadmap from recommendations."""

    def __init__(self, recommendations: list[dict]) -> None:
        self.recommendations = recommendations

    def generate(self) -> dict:
        """Produce a phase-wise implementation roadmap dict."""
        log.info(
            "Generating roadmap from %d recommendations", len(self.recommendations)
        )

        phases = self._build_phases()
        total_savings = round(
            sum(r.get("estimated_monthly_savings", 0.0) for r in self.recommendations), 2
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "phases": phases,
            "total_estimated_monthly_savings": total_savings,
            "implementation_summary": self._build_summary(phases, total_savings),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_phases(self) -> list[dict]:
        """Bucket recommendations into three phases by effort level."""
        phases: list[dict] = []
        for phase_num, label, effort, timeline in _PHASE_DEFS:
            items = sorted(
                [
                    r
                    for r in self.recommendations
                    if r.get("effort_level", "").lower() == effort
                ],
                key=lambda r: r.get("estimated_monthly_savings", 0.0),
                reverse=True,
            )
            phase_savings = round(
                sum(r.get("estimated_monthly_savings", 0.0) for r in items), 2
            )
            phases.append({
                "phase": phase_num,
                "name": label,
                "effort_level": effort,
                "timeline": timeline,
                "items": items,
                "item_count": len(items),
                "total_estimated_monthly_savings": phase_savings,
            })
        return phases

    @staticmethod
    def _build_summary(phases: list[dict], total_savings: float) -> str:
        """Build a brief text summary of the roadmap."""
        phase_parts: list[str] = []
        for phase in phases:
            count = phase["item_count"]
            if count == 0:
                continue
            phase_parts.append(
                f"Phase {phase['phase']} ({phase['name']}): "
                f"{count} item{'s' if count != 1 else ''} "
                f"saving ~${phase['total_estimated_monthly_savings']:,.2f}"
            )

        if not phase_parts:
            return "No actionable recommendations at this time."

        lines = " | ".join(phase_parts)
        return (
            f"{lines}. "
            f"Total estimated savings: ${total_savings:,.2f}/month."
        )
