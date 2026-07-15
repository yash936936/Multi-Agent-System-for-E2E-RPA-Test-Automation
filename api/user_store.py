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
import threading
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
        self._seeded = False
        self._lock = threading.RLock()

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        with self._lock:
            if self._seeded:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self._seed()
            self._seeded = True

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
        self._ensure_seeded()
        with self._lock:
            return json.loads(self.path.read_text())

    def _save(self, users: dict) -> None:
        with self._lock:
            self.path.write_text(json.dumps(users, indent=2))

    def verify(self, username: str, password: str) -> Optional[dict]:
        users = self._load()
        record = users.get(username)
        if not record or record.get("oauth_provider"):
            return None
        if not _verify(password, record["salt"], record["hash"]):
            return None
        return {
            "tenant_id": record["tenant_id"],
            "role": record["role"],
            "user_id": username,
            "allowed_project_tags": record.get("allowed_project_tags"),
        }

    def user_exists(self, username: str) -> bool:
        return username in self._load()

    def create_user(
        self,
        username: str,
        password: str,
        tenant_id: str = "default",
        role: str = "executor",
        allowed_project_tags: Optional[list[str]] = None,
    ) -> None:
        self._ensure_seeded()
        with self._lock:
            users = self._load()
            if username in users:
                raise ValueError(f"User '{username}' already exists")
            users[username] = {
                "tenant_id": tenant_id,
                "role": role,
                "allowed_project_tags": allowed_project_tags,
                **_new_hash(password),
            }
            self._save(users)

    def set_allowed_project_tags(self, username: str, tags: Optional[list[str]]) -> None:
        """
        Phase K (decisions.md D-032): admin-only management operation --
        set (or clear, with tags=None) a user's project-tag restriction.
        Raises ValueError if the user doesn't exist, same convention as
        create_user's "already exists" check.
        """
        self._ensure_seeded()
        with self._lock:
            users = self._load()
            if username not in users:
                raise ValueError(f"User '{username}' does not exist")
            users[username]["allowed_project_tags"] = tags
            self._save(users)

    def find_or_create_oauth_user(
        self, username: str, provider: str, tenant_id: str = "default", role: str = "executor"
    ) -> dict:
        """
        Looks up a user previously linked to `provider`, or creates one on
        first login via that provider.

        SECURITY: OAuth identities are namespaced as "{provider}:{username}"
        (e.g. "github:yash"), never the bare username. Previously this used
        the bare username as the lookup/storage key, which meant an OAuth
        identity could collide with an unrelated local password-based
        account of the same name -- e.g. a local admin account "yash" would
        be silently handed over (tenant_id, role, and all) to anyone who
        controls a GitHub account also named "yash", with no password
        check at all. Namespacing makes that collision structurally
        impossible: "github:yash" can never equal the local key "yash".
        """
        self._ensure_seeded()
        key = f"{provider}:{username}"
        with self._lock:
            users = self._load()
            record = users.get(key)
            if record is None:
                record = {"tenant_id": tenant_id, "role": role, "oauth_provider": provider, "oauth_username": username}
                users[key] = record
                self._save(users)
            elif record.get("oauth_provider") != provider:
                # Defense in depth: even under the namespaced scheme this
                # should be unreachable, but never hand back a record that
                # wasn't actually created for this provider.
                raise ValueError(f"Account key '{key}' exists but is not a {provider} OAuth account")
        return {
            "tenant_id": record["tenant_id"],
            "role": record["role"],
            "user_id": key,
            "allowed_project_tags": record.get("allowed_project_tags"),
        }


user_store = UserStore()
