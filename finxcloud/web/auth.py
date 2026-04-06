"""FinXCloud Web UI — Authentication module.

Simple JWT-based session auth with configurable credentials via env vars.
PoC-appropriate: no database, no OAuth — just username/password + JWT tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

import jwt
from fastapi import Cookie, HTTPException, Request

# Config via env vars (defaults for local dev)
ADMIN_USERNAME = os.environ.get("FINXCLOUD_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("FINXCLOUD_ADMIN_PASS", "admin")
JWT_SECRET = os.environ.get("FINXCLOUD_JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_HOURS = int(os.environ.get("FINXCLOUD_JWT_EXPIRY_HOURS", "24"))


def verify_password(plain: str, expected: str) -> bool:
    """Constant-time comparison of plaintext password against expected."""
    return hmac.compare_digest(plain.encode(), expected.encode())


def create_token(username: str) -> str:
    """Create a JWT token for an authenticated user."""
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token. Returns payload or None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def authenticate(username: str, password: str) -> Optional[str]:
    """Validate credentials and return a JWT token, or None on failure."""
    if username == ADMIN_USERNAME and verify_password(password, ADMIN_PASSWORD):
        return create_token(username)
    return None


async def require_auth(request: Request) -> dict:
    """FastAPI dependency: extract and validate auth from cookie or header.

    Raises HTTPException 401 if not authenticated.
    """
    token = None

    # Check Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # Fall back to cookie
    if not token:
        token = request.cookies.get("finxcloud_token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


def hash_password_for_static(password: str) -> str:
    """SHA-256 hash of a password for embedding in static HTML gate."""
    return hashlib.sha256(password.encode()).hexdigest()
