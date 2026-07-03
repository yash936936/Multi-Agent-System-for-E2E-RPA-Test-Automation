import hashlib
import os
import paramiko
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class FileAdapter:
    """
    Phase 15: Validates file system state (Local & SFTP).
    Detect-only: Does not create, move, or delete files.
    """
    capability_type: CapabilityType = CapabilityType.FILE_SYSTEM

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        action = params.get("action", "local_stat")
        
        try:
            if action.startswith("local_"):
                return self._handle_local(action, params, expected)
            elif action.startswith("sftp_"):
                return self._handle_sftp(action, params, expected)
            else:
                return self._fail(f"Unknown action: {action}")
        except Exception as e:
            return self._fail(f"Execution error: {str(e)}")

    def _handle_local(self, action, params, expected):
        path = params.get("path")
        if not path: return self._fail("Missing 'path'")
        
        evidence = {"path": path, "exists": os.path.exists(path)}
        passed = True
        
        if expected.get("exists") is not None:
            if evidence["exists"] != expected["exists"]:
                passed = False
                
        if evidence["exists"] and os.path.isfile(path):
            stat = os.stat(path)
            evidence["size_bytes"] = stat.st_size
            
            if expected.get("min_size_bytes") and stat.st_size < expected["min_size_bytes"]:
                passed = False
                evidence["size_mismatch"] = True
                
            if action == "local_hash":
                algorithm = params.get("hash_algorithm", "sha256")
                file_hash = self._calculate_hash(path, algorithm)
                evidence["hash"] = file_hash
                if expected.get("hash") and file_hash != expected["hash"]:
                    passed = False
                    evidence["hash_mismatch"] = True
                    
        return CapabilityCheckResult(
            capability=self.capability_type, passed=passed, 
            confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
        )

    def _handle_sftp(self, action, params, expected):
        host = params.get("host")
        port = params.get("port", 22)
        username = params.get("username")
        password = params.get("password")
        path = params.get("path")
        
        if not all([host, username, password, path]):
            return self._fail("Missing SFTP credentials or path")
            
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sftp = None
        
        try:
            client.connect(host, port=port, username=username, password=password, timeout=10)
            sftp = client.open_sftp()
            
            stat = sftp.stat(path)
            evidence = {"path": path, "exists": True, "size_bytes": stat.st_size}
            passed = True
            
            if expected.get("min_size_bytes") and stat.st_size < expected["min_size_bytes"]:
                passed = False
                
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        # Debug Fix: Catch OSError to handle both FileNotFoundError and generic IOError from paramiko
        except OSError:
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=1.0,
                evidence={"path": path, "exists": False, "error": "File not found on SFTP"}, escalate=False
            )
        finally:
            if sftp: sftp.close()
            client.close()

    def _calculate_hash(self, file_path, algorithm="sha256"):
        h = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False
        )