import os
import json
import secrets
from cryptography.fernet import Fernet
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-AURA-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

class SecretVault:
    """Local encrypted-at-rest vault for target system credentials."""
    def __init__(self):
        os.makedirs("config", exist_ok=True)
        self.key_path = "config/vault.key"
        self.secrets_path = "config/secrets.json"
        self._ensure_key()
        self.cipher = Fernet(self._load_key())

    def _ensure_key(self):
        if not os.path.exists(self.key_path):
            with open(self.key_path, "wb") as f:
                f.write(Fernet.generate_key())

    def _load_key(self):
        with open(self.key_path, "rb") as f:
            return f.read()

    def _load_secrets(self):
        if not os.path.exists(self.secrets_path):
            return {}
        with open(self.secrets_path, "r") as f:
            return json.load(f)

    def _save_secrets(self, data):
        with open(self.secrets_path, "w") as f:
            json.dump(data, f, indent=2)

    def set(self, key: str, value: str):
        secrets_dict = self._load_secrets()
        secrets_dict[key] = self.cipher.encrypt(value.encode()).decode()
        self._save_secrets(secrets_dict)

    def get(self, key: str) -> str | None:
        secrets_dict = self._load_secrets()
        if key not in secrets_dict: return None
        return self.cipher.decrypt(secrets_dict[key].encode()).decode()

vault = SecretVault()

# Load expected API key from environment or generate a default for local dev
EXPECTED_API_KEY = os.getenv("AURA_API_KEY", "aura-dev-key-change-me")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API Key")