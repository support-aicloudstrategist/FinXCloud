"""SMTP email sender for FinXCloud reports and notifications."""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger("finxcloud.email")


class EmailConfig:
    """SMTP configuration loaded from environment variables."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host or os.environ.get("FINXCLOUD_SMTP_HOST", "")
        self.smtp_port = smtp_port or int(os.environ.get("FINXCLOUD_SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("FINXCLOUD_SMTP_USER", "")
        self.smtp_password = smtp_password or os.environ.get("FINXCLOUD_SMTP_PASSWORD", "")
        self.from_address = from_address or os.environ.get(
            "FINXCLOUD_FROM_EMAIL", self.smtp_user
        )
        self.use_tls = use_tls

    @property
    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)


def send_email(
    config: EmailConfig,
    to_addresses: list[str],
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> bool:
    """Send an email via SMTP.

    Returns True on success, False on failure.
    """
    if not config.is_configured:
        log.error(
            "Email not configured. Set FINXCLOUD_SMTP_HOST, FINXCLOUD_SMTP_USER, "
            "and FINXCLOUD_SMTP_PASSWORD environment variables."
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.from_address
    msg["To"] = ", ".join(to_addresses)

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if config.use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(config.smtp_user, config.smtp_password)
                server.sendmail(config.from_address, to_addresses, msg.as_string())
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
                server.login(config.smtp_user, config.smtp_password)
                server.sendmail(config.from_address, to_addresses, msg.as_string())

        log.info("Email sent to %s", ", ".join(to_addresses))
        return True
    except Exception as e:
        log.error("Failed to send email: %s", e)
        return False
