"""HTML output writer for FinXCloud AWS cost optimization reports."""

import logging
import os
from pathlib import Path

from jinja2 import Template

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedded Jinja2 HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinXCloud &mdash; AWS Cost Optimization Report</title>
<style>
  :root {
    --green: #16a34a;
    --green-bg: #dcfce7;
    --red: #dc2626;
    --red-bg: #fee2e2;
    --gray-50: #f9fafb;
    --gray-100: #f3f4f6;
    --gray-200: #e5e7eb;
    --gray-700: #374151;
    --gray-900: #111827;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    color: var(--gray-900);
    background: var(--gray-50);
    line-height: 1.6;
    padding: 2rem 1rem;
  }
  .container { max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 1.75rem; margin-bottom: 0.25rem; }
  h2 { font-size: 1.35rem; margin: 2rem 0 1rem; border-bottom: 2px solid var(--gray-200); padding-bottom: 0.4rem; }
  h3 { font-size: 1.1rem; margin: 1.5rem 0 0.5rem; }
  .subtitle { color: var(--gray-700); font-size: 0.95rem; margin-bottom: 2rem; }

  /* Metric cards */
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .card {
    background: #fff; border-radius: 8px; padding: 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  .card .label { font-size: 0.85rem; color: var(--gray-700); }
  .card .value { font-size: 1.5rem; font-weight: 700; margin-top: 0.25rem; }
  .card .value.cost { color: var(--red); }
  .card .value.savings { color: var(--green); }

  /* Tables */
  table { width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  th, td { text-align: left; padding: 0.65rem 1rem; }
  th { background: var(--gray-100); font-size: 0.85rem; text-transform: uppercase; color: var(--gray-700); letter-spacing: 0.03em; }
  tr:not(:last-child) td { border-bottom: 1px solid var(--gray-200); }
  .amount-cost { color: var(--red); font-weight: 600; }
  .amount-savings { color: var(--green); font-weight: 600; }

  /* Phase cards */
  .phase { background: #fff; border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .phase-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
  .phase-header .badge { background: var(--green-bg); color: var(--green); padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; }
  .phase-meta { font-size: 0.9rem; color: var(--gray-700); }

  @media (max-width: 640px) {
    body { padding: 1rem 0.5rem; }
    th, td { padding: 0.5rem 0.6rem; font-size: 0.9rem; }
  }
</style>
</head>
<body>
<div class="container">

<h1>FinXCloud &mdash; AWS Cost Optimization Report</h1>
<p class="subtitle">Generated {{ summary.generated_at }}</p>

<!-- Executive summary metrics -->
<h2>Executive Summary</h2>
<div class="metrics">
  <div class="card">
    <div class="label">Total Resources</div>
    <div class="value">{{ summary.overview.total_resources }}</div>
  </div>
  <div class="card">
    <div class="label">30-Day Cost</div>
    <div class="value cost">${{ "%.2f"|format(summary.overview.total_cost_30d) }}</div>
  </div>
  <div class="card">
    <div class="label">Potential Savings</div>
    <div class="value savings">${{ "%.2f"|format(summary.overview.total_potential_savings) }}</div>
  </div>
  <div class="card">
    <div class="label">Savings Potential</div>
    <div class="value savings">{{ summary.overview.savings_percentage }}%</div>
  </div>
  <div class="card">
    <div class="label">Quick Wins</div>
    <div class="value">{{ summary.quick_wins_count }}</div>
  </div>
</div>

<!-- Top recommendations -->
<h2>Top Recommendations</h2>
{% if summary.top_recommendations %}
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Recommendation</th>
      <th>Category</th>
      <th>Effort</th>
      <th>Est. Savings</th>
    </tr>
  </thead>
  <tbody>
  {% for rec in summary.top_recommendations %}
    <tr>
      <td>{{ loop.index }}</td>
      <td>{{ rec.get("description", rec.get("title", "N/A")) }}</td>
      <td>{{ rec.get("category", "N/A") }}</td>
      <td>{{ rec.get("effort_level", "N/A") }}</td>
      <td class="amount-savings">${{ "%.2f"|format(rec.get("estimated_monthly_savings", 0)) }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No recommendations available.</p>
{% endif %}

<!-- Cost breakdown by service -->
<h2>Cost Breakdown &mdash; By Service</h2>
{% if detailed.cost_breakdown.by_service %}
<table>
  <thead><tr><th>Service</th><th>Amount (30d)</th></tr></thead>
  <tbody>
  {% for svc in detailed.cost_breakdown.by_service %}
    <tr>
      <td>{{ svc.get("service", "N/A") }}</td>
      <td class="amount-cost">${{ "%.2f"|format(svc.get("amount", 0)) }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No service cost data available.</p>
{% endif %}

<!-- Cost breakdown by region -->
<h2>Cost Breakdown &mdash; By Region</h2>
{% if detailed.cost_breakdown.by_region %}
<table>
  <thead><tr><th>Region</th><th>Amount (30d)</th></tr></thead>
  <tbody>
  {% for reg in detailed.cost_breakdown.by_region %}
    <tr>
      <td>{{ reg.get("region", "N/A") }}</td>
      <td class="amount-cost">${{ "%.2f"|format(reg.get("amount", 0)) }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No region cost data available.</p>
{% endif %}

<!-- Roadmap -->
<h2>Implementation Roadmap</h2>
{% for phase in roadmap.phases %}
<div class="phase">
  <div class="phase-header">
    <h3>Phase {{ phase.phase }}: {{ phase.name }}</h3>
    <span class="badge">${{ "%.2f"|format(phase.total_estimated_monthly_savings) }} savings</span>
  </div>
  <p class="phase-meta">
    {{ phase.item_count }} item{{ "s" if phase.item_count != 1 else "" }}
    &middot; Timeline: {{ phase.timeline }}
    &middot; Effort: {{ phase.effort_level }}
  </p>
</div>
{% endfor %}

{% if roadmap.implementation_summary %}
<p style="margin-top:1rem;color:var(--gray-700);">{{ roadmap.implementation_summary }}</p>
{% endif %}

</div><!-- /.container -->
</body>
</html>
""")


class HTMLWriter:
    """Generate a single-page HTML cost optimization report."""

    def __init__(self, output_dir: str = "reports") -> None:
        self.output_dir = output_dir

    def write(self, summary: dict, detailed: dict, roadmap: dict) -> str:
        """Render the HTML report and write it to disk.

        Returns the absolute path to the generated HTML file.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        file_path = str(Path(self.output_dir) / "finxcloud_report.html")

        log.info("Rendering HTML report")
        html = _HTML_TEMPLATE.render(
            summary=summary,
            detailed=detailed,
            roadmap=roadmap,
        )

        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(html)

        log.info("HTML report written: %s", file_path)
        return file_path
