import httpx
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class SharePointAdapter:
    """
    Phase 16b: Real SharePoint file operations via Microsoft Graph API.

    No dedicated SharePoint adapter existed before this (the gap-check
    doc called it out explicitly: "would need Vision Core since
    SharePoint has no dedicated API integration here"). This talks to
    Graph directly over HTTPS -- app-only auth via the OAuth2 client
    credentials grant (no msal dependency needed, httpx is already a
    project dependency) -- and does real upload/download/list against a
    drive, not just UI-level clicking.

    Auth params: tenant_id, client_id, client_secret (app registration
    with Sites.ReadWrite.All application permission, admin-consented).
    Target params: site_id (or params["drive_id"] directly), file_path
    (path within the drive, e.g. "Shared Documents/report.pdf").
    """

    capability_type: CapabilityType = CapabilityType.SHAREPOINT

    _GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        action = params.get("action", "file_exists")

        drive_id = params.get("drive_id")
        site_id = params.get("site_id")
        file_path = params.get("file_path")

        if not file_path:
            return self._fail("Missing 'file_path'")
        if not drive_id and not site_id:
            return self._fail("Missing 'drive_id' or 'site_id'")

        try:
            token = self._get_token(params)
        except Exception as e:
            return self._fail(f"SharePoint auth error: {str(e)}")

        headers = {"Authorization": f"Bearer {token}"}

        try:
            with httpx.Client(timeout=30.0) as client:
                if not drive_id:
                    site_resp = client.get(f"{self._GRAPH_BASE}/sites/{site_id}/drive", headers=headers)
                    site_resp.raise_for_status()
                    drive_id = site_resp.json()["id"]

                if action == "upload_file":
                    content = params.get("content", "")
                    data = content.encode("utf-8") if isinstance(content, str) else content
                    upload_resp = client.put(
                        f"{self._GRAPH_BASE}/drives/{drive_id}/root:/{file_path}:/content",
                        headers=headers, content=data,
                    )
                    upload_resp.raise_for_status()
                    item = upload_resp.json()
                    evidence = {
                        "file_path": file_path, "action": action,
                        "uploaded_bytes": item.get("size"), "web_url": item.get("webUrl"),
                    }
                    return CapabilityCheckResult(
                        capability=self.capability_type, passed=True, confidence=1.0,
                        evidence=evidence, escalate=False,
                    )

                if action == "list_files":
                    folder_path = params.get("folder_path", "")
                    url = (
                        f"{self._GRAPH_BASE}/drives/{drive_id}/root:/{folder_path}:/children"
                        if folder_path else f"{self._GRAPH_BASE}/drives/{drive_id}/root/children"
                    )
                    list_resp = client.get(url, headers=headers)
                    list_resp.raise_for_status()
                    names = [item["name"] for item in list_resp.json().get("value", [])]
                    passed = True
                    evidence = {"folder_path": folder_path, "file_names": names, "count": len(names)}
                    if expected.get("min_count") is not None and len(names) < expected["min_count"]:
                        passed = False
                        evidence["count_mismatch"] = True
                    return CapabilityCheckResult(
                        capability=self.capability_type, passed=passed,
                        confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
                    )

                if action == "download_file":
                    dl_resp = client.get(f"{self._GRAPH_BASE}/drives/{drive_id}/root:/{file_path}:/content", headers=headers)
                    dl_resp.raise_for_status()
                    text = dl_resp.text
                    evidence = {"file_path": file_path, "size_bytes": len(dl_resp.content)}
                    passed = True
                    if expected.get("content_contains") and expected["content_contains"] not in text:
                        passed = False
                        evidence["missing_expected_content"] = True
                    return CapabilityCheckResult(
                        capability=self.capability_type, passed=passed,
                        confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
                    )

                # default: file_exists (detect-only)
                meta_resp = client.get(f"{self._GRAPH_BASE}/drives/{drive_id}/root:/{file_path}", headers=headers)
                if meta_resp.status_code == 404:
                    passed = expected.get("exists") is False
                    return CapabilityCheckResult(
                        capability=self.capability_type, passed=passed, confidence=1.0,
                        evidence={"file_path": file_path, "exists": False}, escalate=False,
                    )
                meta_resp.raise_for_status()
                item = meta_resp.json()
                evidence = {
                    "file_path": file_path, "exists": True,
                    "size_bytes": item.get("size"), "last_modified": item.get("lastModifiedDateTime"),
                }
                passed = True
                if expected.get("exists") is False:
                    passed = False
                    evidence["unexpected_existence"] = True
                if expected.get("min_size_bytes") and item.get("size", 0) < expected["min_size_bytes"]:
                    passed = False
                    evidence["size_mismatch"] = True
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=passed,
                    confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
                )

        except httpx.HTTPStatusError as e:
            return self._fail(f"Graph API error: {e.response.status_code} - {e.response.text[:300]}")
        except Exception as e:
            return self._fail(f"SharePoint execution error: {str(e)}")

    @staticmethod
    def _get_token(params: dict) -> str:
        import os

        tenant_id = params.get("tenant_id") or os.environ.get("AZURE_TENANT_ID")
        client_id = params.get("client_id") or os.environ.get("AZURE_CLIENT_ID")
        client_secret = params.get("client_secret") or os.environ.get("AZURE_CLIENT_SECRET")

        if not all([tenant_id, client_id, client_secret]):
            raise ValueError(
                "Missing SharePoint app-only credentials -- pass 'tenant_id'/'client_id'/"
                "'client_secret' or set AZURE_TENANT_ID/AZURE_CLIENT_ID/AZURE_CLIENT_SECRET"
            )

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False,
        )
