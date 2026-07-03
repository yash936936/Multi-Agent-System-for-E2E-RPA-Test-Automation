import os
import json
import threading
from datetime import datetime, timezone

class AuditLogger:
    """
    Phase 19: Thread-safe, append-only audit logger for enterprise compliance.
    """
    def __init__(self, filepath: str = "logs/audit.jsonl"):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.filepath = filepath
        self.lock = threading.Lock()

    def log(self, tenant_id: str, user_id: str, action: str, resource: str, details: dict = None):
        record = {
            # Debug Fix: Use timezone-aware UTC datetime to avoid Python 3.12 deprecation warnings
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "details": details or {}
        }
        
        with self.lock:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

# Global singleton
audit_logger = AuditLogger()