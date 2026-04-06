"""PDF output writer for FinXCloud AWS cost optimization reports.

Generates a professional, board-presentation-ready PDF executive summary
using ReportLab.  Installed via the ``pdf`` extra:

    pip install 'finxcloud[pdf]'
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    _HAS_REPORTLAB = True
except ImportError:
    _HAS_REPORTLAB = False


# -- Colour palette -----------------------------------------------------------
_BLUE = colors.HexColor("#1e3a5f")
_GREEN = colors.HexColor("#16a34a")
_RED = colors.HexColor("#dc2626")
_GRAY_100 = colors.HexColor("#f3f4f6")
_GRAY_700 = colors.HexColor("#374151")
_WHITE = colors.white


class PDFWriter:
    """Generate a professional PDF executive summary from scan results."""

    def __init__(self, output_dir: str = "reports") -> None:
        if not _HAS_REPORTLAB:
            raise ImportError(
                "reportlab is required for PDF export. "
                "Install it with: pip install 'finxcloud[pdf]'"
            )
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(
        self,
        summary: dict,
        detailed: dict,
        roadmap: dict,
        *,
        tag_allocation: dict | None = None,
    ) -> str:
        """Render the PDF report and write it to disk.

        Returns the absolute path to the generated PDF file.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        file_path = str(Path(self.output_dir) / "finxcloud_report.pdf")

        log.info("Rendering PDF report")
        doc = SimpleDocTemplate(
            file_path,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        elements = self._build_elements(summary, detailed, roadmap, tag_allocation, styles)
        doc.build(elements)

        log.info("PDF report written: %s", file_path)
        return file_path

    def write_bytes(
        self,
        summary: dict,
        detailed: dict,
        roadmap: dict,
        *,
        tag_allocation: dict | None = None,
    ) -> bytes:
        """Render the PDF in memory and return the raw bytes."""
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()
        elements = self._build_elements(summary, detailed, roadmap, tag_allocation, styles)
        doc.build(elements)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_elements(
        self,
        summary: dict,
        detailed: dict,
        roadmap: dict,
        tag_allocation: dict | None,
        styles,
    ) -> list:
        elements: list = []

        # Custom styles
        title_style = ParagraphStyle(
            "PDFTitle",
            parent=styles["Title"],
            fontSize=22,
            textColor=_BLUE,
            spaceAfter=4 * mm,
        )
        heading_style = ParagraphStyle(
            "PDFHeading",
            parent=styles["Heading2"],
            fontSize=14,
            textColor=_BLUE,
            spaceBefore=8 * mm,
            spaceAfter=4 * mm,
        )
        body_style = ParagraphStyle(
            "PDFBody",
            parent=styles["Normal"],
            fontSize=10,
            textColor=_GRAY_700,
        )
        footer_style = ParagraphStyle(
            "PDFFooter",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.gray,
        )

        # Title
        generated = summary.get("generated_at", datetime.now(timezone.utc).isoformat())
        elements.append(Paragraph("FinXCloud - AWS Cost Optimization Report", title_style))
        elements.append(Paragraph(f"Generated {generated[:19].replace('T', ' ')} UTC", body_style))
        elements.append(Spacer(1, 6 * mm))

        # Executive Summary metrics
        elements.append(Paragraph("Executive Summary", heading_style))
        overview = summary.get("overview", {})
        metrics_data = [
            ["Total Resources", "30-Day Cost", "Potential Savings", "Savings %", "Quick Wins"],
            [
                str(overview.get("total_resources", 0)),
                f"${overview.get('total_cost_30d', 0):,.2f}",
                f"${overview.get('total_potential_savings', 0):,.2f}",
                f"{overview.get('savings_percentage', 0):.1f}%",
                str(summary.get("quick_wins_count", 0)),
            ],
        ]
        elements.append(self._styled_table(metrics_data, col_widths=[3.2 * cm] * 5))
        elements.append(Spacer(1, 4 * mm))

        # Top Recommendations
        recs = summary.get("top_recommendations", [])[:5]
        if recs:
            elements.append(Paragraph("Top 5 Recommendations", heading_style))
            rec_data = [["#", "Recommendation", "Category", "Effort", "Est. Savings/mo"]]
            for i, rec in enumerate(recs, 1):
                rec_data.append([
                    str(i),
                    rec.get("description", rec.get("title", "N/A"))[:60],
                    rec.get("category", "N/A"),
                    rec.get("effort_level", "N/A"),
                    f"${rec.get('estimated_monthly_savings', 0):,.2f}",
                ])
            elements.append(
                self._styled_table(rec_data, col_widths=[1 * cm, 7 * cm, 3 * cm, 2 * cm, 3 * cm])
            )
            elements.append(Spacer(1, 4 * mm))

        # Cost Breakdown by Service
        by_service = detailed.get("cost_breakdown", {}).get("by_service", [])
        if by_service:
            elements.append(Paragraph("Cost Breakdown - By Service", heading_style))
            svc_data = [["Service", "Amount (30d)"]]
            for svc in by_service[:10]:
                svc_data.append([
                    svc.get("service", "N/A"),
                    f"${svc.get('amount', 0):,.2f}",
                ])
            elements.append(self._styled_table(svc_data, col_widths=[10 * cm, 6 * cm]))
            elements.append(Spacer(1, 4 * mm))

        # Cost Breakdown by Region
        by_region = detailed.get("cost_breakdown", {}).get("by_region", [])
        if by_region:
            elements.append(Paragraph("Cost Breakdown - By Region", heading_style))
            reg_data = [["Region", "Amount (30d)"]]
            for reg in by_region[:10]:
                reg_data.append([
                    reg.get("service", reg.get("region", "N/A")),
                    f"${reg.get('amount', 0):,.2f}",
                ])
            elements.append(self._styled_table(reg_data, col_widths=[10 * cm, 6 * cm]))
            elements.append(Spacer(1, 4 * mm))

        # Tag-based Cost Allocation
        if tag_allocation and tag_allocation.get("by_tag"):
            elements.append(Paragraph("Cost Allocation by Tags", heading_style))
            for tag_group in tag_allocation["by_tag"]:
                tag_key = tag_group.get("tag_key", "Unknown")
                elements.append(
                    Paragraph(f"Tag: {tag_key}", ParagraphStyle(
                        "TagLabel", parent=body_style, fontSize=11,
                        textColor=_BLUE, spaceBefore=3 * mm, spaceAfter=2 * mm,
                    ))
                )
                tag_data = [["Tag Value", "Amount (30d)"]]
                for val in tag_group.get("values", []):
                    tag_data.append([
                        val.get("value", "Untagged"),
                        f"${val.get('amount', 0):,.2f}",
                    ])
                elements.append(self._styled_table(tag_data, col_widths=[10 * cm, 6 * cm]))
            elements.append(Spacer(1, 4 * mm))

        # Roadmap Summary
        phases = roadmap.get("phases", [])
        if phases:
            elements.append(Paragraph("Implementation Roadmap", heading_style))
            phase_data = [["Phase", "Name", "Items", "Timeline", "Est. Savings/mo"]]
            for phase in phases:
                phase_data.append([
                    str(phase.get("phase", "")),
                    phase.get("name", ""),
                    str(phase.get("item_count", 0)),
                    phase.get("timeline", ""),
                    f"${phase.get('total_estimated_monthly_savings', 0):,.2f}",
                ])
            elements.append(
                self._styled_table(phase_data, col_widths=[1.5 * cm, 5 * cm, 2 * cm, 4 * cm, 3.5 * cm])
            )

        impl_summary = roadmap.get("implementation_summary")
        if impl_summary:
            elements.append(Spacer(1, 3 * mm))
            elements.append(Paragraph(impl_summary, body_style))

        # Footer
        elements.append(Spacer(1, 10 * mm))
        elements.append(
            Paragraph("Generated by FinXCloud - AWS Cost Optimization Tool", footer_style)
        )
        return elements

    @staticmethod
    def _styled_table(data: list[list], col_widths: list | None = None) -> Table:
        """Create a consistently styled ReportLab table."""
        table = Table(data, colWidths=col_widths, repeatRows=1)
        style_commands = [
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            # Body rows
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            # Alternating row colours
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _GRAY_100]),
            # Grid
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ]
        table.setStyle(TableStyle(style_commands))
        return table
