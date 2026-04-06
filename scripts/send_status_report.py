#!/usr/bin/env python3
"""Generate and send the daily status report for AICloud Strategist.

Usage:
    # Set SMTP env vars first, then:
    python scripts/send_status_report.py --to support@aicloudstrategist.com

    # Or generate HTML only (no send):
    python scripts/send_status_report.py --html-only --output reports/status_report.html

Environment variables required for sending:
    FINXCLOUD_SMTP_HOST      — SMTP server (e.g. smtp.gmail.com, email-smtp.us-east-1.amazonaws.com)
    FINXCLOUD_SMTP_PORT      — SMTP port (default: 587)
    FINXCLOUD_SMTP_USER      — SMTP username
    FINXCLOUD_SMTP_PASSWORD  — SMTP password or app-specific password
    FINXCLOUD_FROM_EMAIL     — Sender address (defaults to SMTP_USER)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finxcloud.email.sender import EmailConfig, send_email, send_email_ses
from finxcloud.email.templates import status_report_html


def build_status_data() -> dict:
    """Build today's status report data."""
    today = date.today().isoformat()

    tasks = [
        {"id": "AIC-1", "title": "Hire first engineer and create hiring plan", "owner": "CEO", "status": "Done", "next_steps": "Hired CTO, CMO, Head of Sales — all onboarded"},
        {"id": "AIC-2", "title": "Define technical service catalog and delivery framework", "owner": "CTO", "status": "Done", "next_steps": "Catalog ready for client-facing use"},
        {"id": "AIC-3", "title": "Set up company project structure and initial codebase", "owner": "CTO", "status": "Done", "next_steps": "Repo and project scaffolding complete"},
        {"id": "AIC-4", "title": "Website creation", "owner": "CTO", "status": "Done", "next_steps": "Website artifacts delivered"},
        {"id": "AIC-5", "title": "Hiring resources", "owner": "CEO", "status": "Done", "next_steps": "All key hires completed"},
        {"id": "AIC-6", "title": "Build go-to-market marketing plan", "owner": "CMO", "status": "Done", "next_steps": "GTM plan ready; execution underway"},
        {"id": "AIC-7", "title": "Define sales process and build outbound pipeline", "owner": "Head of Sales", "status": "Done", "next_steps": "Pipeline framework in place"},
        {"id": "AIC-8", "title": "Start next set of activities", "owner": "CEO", "status": "Done", "next_steps": "Delegated execution tasks to all teams"},
        {"id": "AIC-9", "title": "Execute content marketing (1)", "owner": "CMO", "status": "Done", "next_steps": "Content calendar and initial posts delivered"},
        {"id": "AIC-10", "title": "Execute content marketing (2)", "owner": "CMO", "status": "Done", "next_steps": "Lead capture and nurture sequences live"},
        {"id": "AIC-11", "title": "Execute outbound sales — research, outreach, pipeline", "owner": "Head of Sales", "status": "Done", "next_steps": "Target list built, outreach templates ready"},
        {"id": "AIC-12", "title": "Build client engagement templates and delivery artifacts", "owner": "CTO", "status": "Done", "next_steps": "SOWs, onboarding docs, delivery templates complete"},
        {"id": "AIC-13", "title": "CMO ↔ Sales alignment — MQL/SQL and handoff", "owner": "CMO", "status": "Done", "next_steps": "Lead handoff process documented"},
        {"id": "AIC-14", "title": "Sales: board directives — pricing, outreach, India targets", "owner": "Head of Sales", "status": "Done", "next_steps": "Pricing tiers set, India outreach plan active"},
        {"id": "AIC-15", "title": "CMO: board directives — multi-channel, Google, social", "owner": "CMO", "status": "Done", "next_steps": "Multi-channel marketing strategy deployed"},
        {"id": "AIC-16", "title": "Build first tool", "owner": "CEO", "status": "Done", "next_steps": "FinXCloud tool initiative kicked off"},
        {"id": "AIC-17", "title": "FinXCloud PoC — AWS cost optimization tool", "owner": "CTO", "status": "Done", "next_steps": "Core scan engine working"},
        {"id": "AIC-18", "title": "Add OpenSearch scanner to FinXCloud", "owner": "CTO", "status": "Done", "next_steps": "OpenSearch analyzer integrated"},
        {"id": "AIC-19", "title": "Build FinXCloud Web UI dashboard", "owner": "CTO", "status": "In Progress", "next_steps": "FastAPI + React dashboard in progress"},
        {"id": "AIC-20", "title": "Initialize git repo and push to GitHub", "owner": "CTO", "status": "Done", "next_steps": "Repo pushed"},
        {"id": "AIC-21", "title": "Repository management", "owner": "CEO", "status": "Done", "next_steps": "Repo governance set up"},
        {"id": "AIC-22", "title": "Add S3 storage backend for FinXCloud", "owner": "CTO", "status": "Done", "next_steps": "S3 upload/read + deploy added"},
        {"id": "AIC-23", "title": "Status Update + Email Integration", "owner": "CEO", "status": "In Progress", "next_steps": "Email module built; sending report"},
    ]

    team_summary = {
        "CEO": {"tasks_done": 4, "summary": "Hired all 3 key roles, initiated FinXCloud product build, coordinated cross-team execution."},
        "CTO": {"tasks_done": 8, "summary": "Built FinXCloud end-to-end (scan engine, OpenSearch, Web UI, S3, Git repo). Created service catalog, delivery framework, client templates."},
        "CMO": {"tasks_done": 5, "summary": "Delivered GTM plan and content calendar. Launched multi-channel strategy. Aligned with Sales on MQL/SQL handoff."},
        "Head of Sales": {"tasks_done": 3, "summary": "Built sales process and outbound pipeline. Executed target research and outreach templates. Implemented board pricing and India market directives."},
    }

    next_priorities = [
        "CTO: Client demo prep for FinXCloud; iterate on dashboard",
        "CMO: Continue content execution; measure lead capture week 1",
        "Head of Sales: Begin active outreach to pipeline; track conversions",
        "CEO: Review first client engagement opportunities; set week 2 OKRs",
    ]

    return {
        "date": today,
        "tasks": tasks,
        "team_summary": team_summary,
        "next_priorities": next_priorities,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate and send AICloud Strategist status report")
    parser.add_argument("--to", default="support@aicloudstrategist.com", help="Recipient email(s), comma-separated")
    parser.add_argument("--from-email", default=os.environ.get("FINXCLOUD_FROM_EMAIL", ""), help="Sender email address")
    parser.add_argument("--subject", default=None, help="Email subject")
    parser.add_argument("--via", choices=["ses", "smtp"], default="ses", help="Send via AWS SES API (default) or SMTP")
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"), help="AWS region for SES")
    parser.add_argument("--html-only", action="store_true", help="Generate HTML file only, do not send")
    parser.add_argument("--output", default="reports/status_report.html", help="Output HTML file path")
    args = parser.parse_args()

    data = build_status_data()
    html = status_report_html(
        date=data["date"],
        tasks=data["tasks"],
        team_summary=data["team_summary"],
        next_priorities=data["next_priorities"],
    )

    # Always save the HTML
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML report saved to: {output_path}")

    if args.html_only:
        return

    subject = args.subject or f"AICloud Strategist — Daily Status Report — {data['date']}"
    recipients = [addr.strip() for addr in args.to.split(",")]
    from_email = args.from_email

    print(f"Sending via {args.via.upper()} to: {', '.join(recipients)}")

    if args.via == "ses":
        if not from_email:
            print("Error: --from-email is required (or set FINXCLOUD_FROM_EMAIL)")
            sys.exit(1)
        success = send_email_ses(recipients, subject, html, from_email, region=args.region)
    else:
        config = EmailConfig()
        if not config.is_configured:
            print(
                "\nSMTP not configured. Set FINXCLOUD_SMTP_HOST, FINXCLOUD_SMTP_USER, "
                "FINXCLOUD_SMTP_PASSWORD. Or use --via ses with AWS credentials."
            )
            sys.exit(1)
        success = send_email(config, recipients, subject, html)

    if success:
        print("Email sent successfully.")
    else:
        print("Failed to send email.")
        sys.exit(1)


if __name__ == "__main__":
    main()
