"""
Local user store — api/user_store.py

There is no user database anywhere in AURA yet (STATUS.md: "no login
endpoint exists"). This adds the minimum needed to make /auth/login real
without pulling in a new dependency: a JSON file under config/users.json,
passwords hashed with PBKDF2-HMAC-SHA256 (stdlib `hashlib`, no bcrypt/
passlib dependency needed), seeded on first run with one admin user per
tenant "default".

The seed password is either read from the AURA_ADMIN_PASSWORD env var or
generated and printed once to stderr -- it is never written in plaintext
to disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

from config.settings import settings

_ITERATIONS = 260_000


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS).hex()


def _new_hash(password: str) -> dict:
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": _hash_password(password, salt)}


def _verify(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    return secrets.compare_digest(_hash_password(password, salt), hash_hex)


class UserStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (settings.project_root / "config" / "users.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._seed()

    def _seed(self) -> None:
        admin_password = os.environ.get("AURA_ADMIN_PASSWORD")
        generated = admin_password is None
        if generated:
            admin_password = secrets.token_urlsafe(12)

        users = {
            "admin": {
                "tenant_id": "default",
                "role": "admin",
                **_new_hash(admin_password),
            }
        }
        self.path.write_text(json.dumps(users, indent=2))

        if generated:
            print(
                f"[AURA] Seeded default admin user 'admin' with generated password: {admin_password}\n"
                "        Set AURA_ADMIN_PASSWORD before first run to control this yourself. "
                "This password is shown only once.",
                file=sys.stderr,
            )

    def _load(self) -> dict:
        return json.loads(self.path.read_text())

    def verify(self, username: str, password: str) -> Optional[dict]:
        users = self._load()
        record = users.get(username)
        if not record:
            return None
        if not _verify(password, record["salt"], record["hash"]):
            return None
        return {"tenant_id": record["tenant_id"], "role": record["role"], "user_id": username}

    def create_user(self, username: str, password: str, tenant_id: str, role: str) -> None:
        users = self._load()
        users[username] = {"tenant_id": tenant_id, "role": role, **_new_hash(password)}
        self.path.write_text(json.dumps(users, indent=2))


user_store = UserStore()
