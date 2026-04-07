"""AWS credential management for FinXCloud cost optimization."""

import logging
from dataclasses import dataclass, field
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

log = logging.getLogger(__name__)


@dataclass
class AWSCredentials:
    """Container for AWS authentication credentials."""

    access_key_id: str
    secret_access_key: str
    session_token: Optional[str] = None
    region: str = "us-east-1"
    profile: Optional[str] = None
    role_arn: Optional[str] = None


def create_session(creds: AWSCredentials) -> boto3.Session:
    """Create a boto3 session from the provided credentials.

    Args:
        creds: AWS credentials to use for the session.

    Returns:
        A configured boto3 Session.

    Raises:
        BotoCoreError: If the session cannot be created.
    """
    session_kwargs: dict = {"region_name": creds.region}

    if creds.profile:
        session_kwargs["profile_name"] = creds.profile
    else:
        session_kwargs["aws_access_key_id"] = creds.access_key_id
        session_kwargs["aws_secret_access_key"] = creds.secret_access_key
        if creds.session_token:
            session_kwargs["aws_session_token"] = creds.session_token

    try:
        session = boto3.Session(**session_kwargs)
    except BotoCoreError as exc:
        raise BotoCoreError(
            f"Failed to create AWS session: {exc}"
        ) from exc

    if creds.role_arn:
        try:
            session = _assume_role(session, creds.role_arn, creds.region)
        except Exception as exc:
            log.warning(
                "AssumeRole failed for %s — falling back to direct credentials. Error: %s",
                creds.role_arn, exc,
            )

    return session


def _assume_role(
    session: boto3.Session, role_arn: str, region: str = "us-east-1"
) -> boto3.Session:
    """Assume an IAM role and return a new session with temporary credentials."""
    sts = session.client("sts")
    try:
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="FinXCloud-AssumedRole",
        )
    except sts.exceptions.ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "AccessDenied":
            # Extract account IDs for a helpful error message
            caller = sts.get_caller_identity()
            source_account = caller.get("Account", "unknown")
            target_account = role_arn.split(":")[4] if ":" in role_arn else "unknown"
            raise RuntimeError(
                f"Cannot assume role {role_arn}. "
                f"Your IAM user in account {source_account} is not authorized to assume this role in account {target_account}. "
                f"To fix this: (1) ensure the role exists in the target account, "
                f"(2) add a trust policy on the role allowing account {source_account}, and "
                f"(3) grant your IAM user sts:AssumeRole permission. "
                f"Alternatively, use access keys that belong directly to account {target_account} without a role ARN."
            ) from exc
        raise
    temp = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=temp["AccessKeyId"],
        aws_secret_access_key=temp["SecretAccessKey"],
        aws_session_token=temp["SessionToken"],
        region_name=region,
    )


def validate_credentials(session: boto3.Session) -> dict:
    """Validate AWS credentials by calling STS GetCallerIdentity.

    Args:
        session: An active boto3 session to validate.

    Returns:
        A dict containing Account, Arn, and UserId from the caller identity.

    Raises:
        NoCredentialsError: If no credentials are available in the session.
        ClientError: If the STS call fails (e.g. expired or invalid credentials).
    """
    try:
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        return {
            "Account": identity["Account"],
            "Arn": identity["Arn"],
            "UserId": identity["UserId"],
        }
    except NoCredentialsError:
        raise
    except ClientError:
        raise
    except BotoCoreError as exc:
        raise BotoCoreError(
            f"Credential validation failed: {exc}"
        ) from exc
