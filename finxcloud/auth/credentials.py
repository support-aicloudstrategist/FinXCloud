"""AWS credential management for FinXCloud cost optimization."""

from dataclasses import dataclass, field
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError


@dataclass
class AWSCredentials:
    """Container for AWS authentication credentials."""

    access_key_id: str
    secret_access_key: str
    session_token: Optional[str] = None
    region: str = "us-east-1"
    profile: Optional[str] = None


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
        return boto3.Session(**session_kwargs)
    except BotoCoreError as exc:
        raise BotoCoreError(
            f"Failed to create AWS session: {exc}"
        ) from exc


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
