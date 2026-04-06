"""SQLite-based storage for AWS accounts and scan results (PoC)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

_DB_PATH = os.environ.get(
    "FINXCLOUD_DB_PATH",
    str(Path.home() / ".finxcloud" / "finxcloud.db"),
)

_local = threading.local()


def _get_fernet() -> Fernet:
    """Return a Fernet instance, generating a key file if needed."""
    key_path = Path(_DB_PATH).parent / ".fernet.key"
    if key_path.exists():
        key = key_path.read_bytes().strip()
    else:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        key_path.chmod(0o600)
    return Fernet(key)


def _conn() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        db = Path(_DB_PATH)
        db.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(db))
        _local.conn.row_factory = sqlite3.Row
        _init_tables(_local.conn)
    return _local.conn


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            access_key_enc TEXT NOT NULL,
            secret_key_enc TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'us-east-1',
            role_arn TEXT,
            org_scan INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_scan_at TEXT
        );
        CREATE TABLE IF NOT EXISTS scan_results (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'done',
            result_json TEXT,
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# Account CRUD
# ---------------------------------------------------------------------------

def list_accounts() -> list[dict]:
    rows = _conn().execute(
        "SELECT id, name, region, role_arn, org_scan, created_at, last_scan_at FROM accounts ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_account(account_id: str) -> dict | None:
    row = _conn().execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["access_key"] = _decrypt(d.pop("access_key_enc"))
    d["secret_key"] = _decrypt(d.pop("secret_key_enc"))
    return d


def create_account(
    name: str,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    role_arn: str | None = None,
    org_scan: bool = False,
) -> dict:
    account_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    _conn().execute(
        "INSERT INTO accounts (id, name, access_key_enc, secret_key_enc, region, role_arn, org_scan, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, name, _encrypt(access_key), _encrypt(secret_key), region, role_arn, int(org_scan), now),
    )
    _conn().commit()
    return {"id": account_id, "name": name, "region": region, "role_arn": role_arn, "org_scan": org_scan, "created_at": now}


def update_account(account_id: str, **fields) -> bool:
    allowed = {"name", "access_key", "secret_key", "region", "role_arn", "org_scan"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "access_key":
            sets.append("access_key_enc = ?")
            vals.append(_encrypt(v))
        elif k == "secret_key":
            sets.append("secret_key_enc = ?")
            vals.append(_encrypt(v))
        elif k == "org_scan":
            sets.append("org_scan = ?")
            vals.append(int(v))
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return False
    vals.append(account_id)
    _conn().execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", vals)
    _conn().commit()
    return True


def delete_account(account_id: str) -> bool:
    cur = _conn().execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    _conn().commit()
    return cur.rowcount > 0


def touch_account_scan(account_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _conn().execute("UPDATE accounts SET last_scan_at = ? WHERE id = ?", (now, account_id))
    _conn().commit()


# ---------------------------------------------------------------------------
# Scan result storage
# ---------------------------------------------------------------------------

def save_scan_result(account_id: str, result: dict) -> str:
    scan_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    _conn().execute(
        "INSERT INTO scan_results (id, account_id, scanned_at, status, result_json) VALUES (?, ?, ?, ?, ?)",
        (scan_id, account_id, now, "done", json.dumps(result)),
    )
    _conn().commit()
    touch_account_scan(account_id)
    return scan_id


def get_latest_scan(account_id: str) -> dict | None:
    row = _conn().execute(
        "SELECT * FROM scan_results WHERE account_id = ? ORDER BY scanned_at DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
    return d


def list_scans(account_id: str, limit: int = 10) -> list[dict]:
    rows = _conn().execute(
        "SELECT id, account_id, scanned_at, status FROM scan_results WHERE account_id = ? ORDER BY scanned_at DESC LIMIT ?",
        (account_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
