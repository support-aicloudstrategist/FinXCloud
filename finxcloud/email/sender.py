"""Email sender for FinXCloud reports — supports both SMTP and AWS SES API."""

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

        log.info("Email sent via SMTP to %s", ", ".join(to_addresses))
        return True
    except Exception as e:
        log.error("Failed to send email via SMTP: %s", e)
        return False


def send_email_ses(
    to_addresses: list[str],
    subject: str,
    html_body: str,
    from_address: str,
    text_body: str | None = None,
    region: str | None = None,
    session=None,
) -> bool:
    """Send an email using the AWS SES API directly (no SMTP credentials needed).

    Requires AWS credentials (env vars or boto3 session) with ses:SendEmail permission.
    Returns True on success, False on failure.
    """
    try:
        import boto3
    except ImportError:
        log.error("boto3 is required for SES API sending. Install with: pip install boto3")
        return False

    region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    try:
        if session is None:
            session = boto3.Session(region_name=region)
        ses = session.client("ses", region_name=region)

        body = {"Html": {"Data": html_body, "Charset": "UTF-8"}}
        if text_body:
            body["Text"] = {"Data": text_body, "Charset": "UTF-8"}

        response = ses.send_email(
            Source=from_address,
            Destination={"ToAddresses": to_addresses},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": body,
            },
        )
        message_id = response.get("MessageId", "unknown")
        log.info("Email sent via SES to %s (MessageId: %s)", ", ".join(to_addresses), message_id)
        return True
    except Exception as e:
        log.error("Failed to send email via SES: %s", e)
        return False


def verify_ses_identity(email: str, region: str | None = None, session=None) -> bool:
    """Request SES verification for an email address.

    Returns True if verification request was sent, False on error.
    """
    try:
        import boto3
    except ImportError:
        log.error("boto3 is required for SES operations.")
        return False

    region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    try:
        if session is None:
            session = boto3.Session(region_name=region)
        ses = session.client("ses", region_name=region)
        ses.verify_email_identity(EmailAddress=email)
        log.info("Verification email sent to %s", email)
        return True
    except Exception as e:
        log.error("Failed to request SES verification for %s: %s", email, e)
        return False


def check_ses_identity_status(email: str, region: str | None = None, session=None) -> str:
    """Check SES verification status for an email address.

    Returns 'Success', 'Pending', 'Failed', 'TemporaryFailure', or 'NotStarted'.
    """
    try:
        import boto3
    except ImportError:
        return "Error"

    region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    try:
        if session is None:
            session = boto3.Session(region_name=region)
        ses = session.client("ses", region_name=region)
        response = ses.get_identity_verification_attributes(Identities=[email])
        attrs = response.get("VerificationAttributes", {}).get(email, {})
        return attrs.get("VerificationStatus", "NotStarted")
    except Exception as e:
        log.error("Failed to check SES status for %s: %s", email, e)
        return "Error"
