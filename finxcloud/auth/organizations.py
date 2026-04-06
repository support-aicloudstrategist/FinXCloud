"""AWS Organizations account discovery for FinXCloud cost optimization."""

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def is_organizations_account(session: boto3.Session) -> bool:
    """Check whether the current account belongs to an AWS Organization.

    Args:
        session: An active boto3 session.

    Returns:
        True if the account is part of an Organization, False otherwise.
    """
    try:
        orgs = session.client("organizations")
        orgs.describe_organization()
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "AWSOrganizationsNotInUseException":
            return False
        raise


def list_member_accounts(session: boto3.Session) -> list[dict]:
    """List all active member accounts in the AWS Organization.

    Uses pagination to retrieve every account regardless of Organization size.

    Args:
        session: An active boto3 session with Organizations permissions.

    Returns:
        A list of dicts, each containing id, name, email, and status for an
        active member account.

    Raises:
        ClientError: If the Organizations API call fails.
        BotoCoreError: On underlying SDK errors.
    """
    try:
        orgs = session.client("organizations")
        paginator = orgs.get_paginator("list_accounts")
        accounts: list[dict] = []

        for page in paginator.paginate():
            for account in page["Accounts"]:
                if account["Status"] == "ACTIVE":
                    accounts.append(
                        {
                            "id": account["Id"],
                            "name": account["Name"],
                            "email": account["Email"],
                            "status": account["Status"],
                        }
                    )

        return accounts
    except (ClientError, BotoCoreError):
        raise


def assume_role_session(
    session: boto3.Session,
    account_id: str,
    role_name: str = "OrganizationAccountAccessRole",
    region: str = "us-east-1",
) -> boto3.Session:
    """Assume a role in a member account and return a new session.

    Args:
        session: An active boto3 session used to perform the AssumeRole call.
        account_id: The 12-digit AWS account ID to assume into.
        role_name: The IAM role name to assume in the target account.
        region: The AWS region for the new session.

    Returns:
        A new boto3 Session authenticated with the assumed role credentials.

    Raises:
        ClientError: If the AssumeRole call fails (e.g. access denied,
            role does not exist).
        BotoCoreError: On underlying SDK errors.
    """
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    session_name = f"FinXCloud-{account_id}"

    try:
        sts = session.client("sts")
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
        )
        temp_creds = response["Credentials"]

        return boto3.Session(
            aws_access_key_id=temp_creds["AccessKeyId"],
            aws_secret_access_key=temp_creds["SecretAccessKey"],
            aws_session_token=temp_creds["SessionToken"],
            region_name=region,
        )
    except (ClientError, BotoCoreError):
        raise
