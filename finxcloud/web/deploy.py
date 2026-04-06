"""Deploy FinXCloud dashboard to S3 with static website hosting."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from finxcloud.web.auth import hash_password_for_static

log = logging.getLogger("finxcloud.deploy")

STATIC_DIR = Path(__file__).parent / "static"


def build_static_dashboard(report_data: dict, deploy_password: str | None = None) -> str:
    """Build a self-contained HTML dashboard with embedded report data.

    Reads the dashboard template and injects report JSON so the page
    works without any backend. Optionally adds a client-side password gate.
    """
    template_path = STATIC_DIR / "index.html"
    html = template_path.read_text(encoding="utf-8")

    # Build the embedded script
    parts = ["\n<script>\n"]

    # Add password gate if configured
    if deploy_password:
        password_hash = hash_password_for_static(deploy_password)
        parts.append(
            "// Client-side password gate for static deployment\n"
            "var FINXCLOUD_DEPLOY_PASSWORD_HASH = '" + password_hash + "';\n"
            "var FINXCLOUD_STATIC_AUTH = true;\n"
        )

    parts.append(
        "// Embedded report data for static/S3 deployment\n"
        "var FINXCLOUD_EMBEDDED_DATA = "
        + json.dumps(report_data, default=str)
        + ";\n"
        "// Auto-render on load in static mode\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "  document.querySelector('.scan-panel').style.display = 'none';\n"
        "  if (typeof FINXCLOUD_STATIC_AUTH !== 'undefined' && FINXCLOUD_STATIC_AUTH) {\n"
        "    showStaticLogin();\n"
        "  } else {\n"
        "    document.getElementById('loginOverlay').classList.add('hidden');\n"
        "    renderDashboard(FINXCLOUD_EMBEDDED_DATA);\n"
        "  }\n"
        "});\n"
        "function showStaticLogin() {\n"
        "  document.getElementById('loginOverlay').classList.remove('hidden');\n"
        "  document.getElementById('loginForm').onsubmit = async function(e) {\n"
        "    e.preventDefault();\n"
        "    var pass = document.getElementById('loginPass').value;\n"
        "    var buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(pass));\n"
        "    var hash = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2,'0')).join('');\n"
        "    if (hash === FINXCLOUD_DEPLOY_PASSWORD_HASH) {\n"
        "      document.getElementById('loginOverlay').classList.add('hidden');\n"
        "      renderDashboard(FINXCLOUD_EMBEDDED_DATA);\n"
        "    } else {\n"
        "      document.getElementById('loginError').classList.add('show');\n"
        "    }\n"
        "  };\n"
        "}\n"
    )

    parts.append("</script>\n")
    embedded_script = "".join(parts)
    html = html.replace("</body>", embedded_script + "</body>")
    return html


def deploy_to_s3(
    session: boto3.Session,
    bucket: str,
    report_data: dict,
    prefix: str = "",
    deploy_password: str | None = None,
) -> str:
    """Deploy the dashboard to an S3 bucket with static website hosting.

    Returns the public website URL.
    """
    s3 = session.client("s3")
    region = session.region_name or "us-east-1"

    # Ensure bucket exists
    try:
        s3.head_bucket(Bucket=bucket)
        log.info("Bucket %s already exists", bucket)
    except ClientError:
        log.info("Creating bucket %s", bucket)
        create_params = {"Bucket": bucket}
        if region != "us-east-1":
            create_params["CreateBucketConfiguration"] = {
                "LocationConstraint": region
            }
        s3.create_bucket(**create_params)

    # Enable static website hosting
    s3.put_bucket_website(
        Bucket=bucket,
        WebsiteConfiguration={
            "IndexDocument": {"Suffix": "index.html"},
            "ErrorDocument": {"Key": "index.html"},
        },
    )

    # Set public access policy
    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{bucket}/*",
        }],
    })

    # Disable block public access
    try:
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
    except ClientError as e:
        log.warning("Could not update public access block: %s", e)

    try:
        s3.put_bucket_policy(Bucket=bucket, Policy=policy)
    except ClientError as e:
        log.warning("Could not set bucket policy: %s", e)

    # Build self-contained HTML
    html = build_static_dashboard(report_data, deploy_password=deploy_password)

    # Upload
    key_prefix = f"{prefix.strip('/')}/" if prefix else ""
    index_key = f"{key_prefix}index.html"

    s3.put_object(
        Bucket=bucket,
        Key=index_key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
    )
    log.info("Uploaded dashboard to s3://%s/%s", bucket, index_key)

    # Also upload raw JSON reports for reference
    for name in ("summary", "detailed", "roadmap"):
        if name in report_data:
            json_key = f"{key_prefix}{name}_report.json"
            s3.put_object(
                Bucket=bucket,
                Key=json_key,
                Body=json.dumps(report_data[name], indent=2, default=str).encode("utf-8"),
                ContentType="application/json",
            )

    # Build the public URL
    if region == "us-east-1":
        url = f"http://{bucket}.s3-website-{region}.amazonaws.com"
    else:
        url = f"http://{bucket}.s3-website.{region}.amazonaws.com"

    if key_prefix:
        url = f"{url}/{key_prefix}"

    return url
