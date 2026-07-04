from azure.core.exceptions import ResourceNotFoundError, ClientAuthenticationError
from azure.storage.blob import BlobServiceClient
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class AzureBlobAdapter:
    """
    Phase 16b: Validates and manipulates Azure Blob Storage.

    Unlike CloudAdapter (S3, detect-only), this adapter performs real
    read/write actions when asked -- upload_blob actually writes bytes,
    download_blob actually reads them back, matching the "full read/write
    actions where feasible" scope for the gap-closing pass. blob_exists
    stays detect-only for the common "did this land" check.

    Auth: params["connection_string"], or falls back to the
    AZURE_STORAGE_CONNECTION_STRING env var via
    BlobServiceClient.from_connection_string (never hardcoded).
    """

    capability_type: CapabilityType = CapabilityType.AZURE_BLOB

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        action = params.get("action", "blob_exists")

        container = params.get("container")
        blob_name = params.get("blob_name")
        if not all([container, blob_name]):
            return self._fail("Missing 'container' or 'blob_name'")

        try:
            client = self._client(params)
            blob_client = client.get_blob_client(container=container, blob=blob_name)

            if action == "upload_blob":
                content = params.get("content", "")
                data = content.encode("utf-8") if isinstance(content, str) else content
                blob_client.upload_blob(data, overwrite=params.get("overwrite", True))
                props = blob_client.get_blob_properties()
                evidence = {
                    "container": container, "blob_name": blob_name,
                    "action": action, "uploaded_bytes": props.size,
                }
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=True, confidence=1.0,
                    evidence=evidence, escalate=False,
                )

            if action == "list_blobs":
                container_client = client.get_container_client(container)
                prefix = params.get("prefix", "")
                names = [b.name for b in container_client.list_blobs(name_starts_with=prefix)]
                passed = True
                evidence = {"container": container, "prefix": prefix, "blob_names": names, "count": len(names)}
                if expected.get("min_count") is not None and len(names) < expected["min_count"]:
                    passed = False
                    evidence["count_mismatch"] = True
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=passed,
                    confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
                )

            if action == "download_blob":
                downloaded = blob_client.download_blob().readall()
                text = downloaded.decode("utf-8", errors="replace")
                evidence = {"container": container, "blob_name": blob_name, "size_bytes": len(downloaded)}
                passed = True
                if expected.get("content_contains") and expected["content_contains"] not in text:
                    passed = False
                    evidence["missing_expected_content"] = True
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=passed,
                    confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
                )

            # default: blob_exists (detect-only, mirrors CloudAdapter's S3 shape)
            props = blob_client.get_blob_properties()
            evidence = {
                "container": container, "blob_name": blob_name, "exists": True,
                "size_bytes": props.size, "last_modified": str(props.last_modified),
            }
            passed = True
            if expected.get("exists") is False:
                passed = False
                evidence["unexpected_existence"] = True
            if expected.get("min_size_bytes") and props.size < expected["min_size_bytes"]:
                passed = False
                evidence["size_mismatch"] = True
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed,
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
            )

        except ResourceNotFoundError:
            passed = expected.get("exists") is False
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, confidence=1.0,
                evidence={"container": container, "blob_name": blob_name, "exists": False}, escalate=False,
            )
        except ClientAuthenticationError as e:
            return self._fail(f"Azure authentication error: {str(e)}")
        except Exception as e:
            return self._fail(f"Azure execution error: {str(e)}")

    @staticmethod
    def _client(params: dict) -> BlobServiceClient:
        conn_str = params.get("connection_string")
        if conn_str:
            return BlobServiceClient.from_connection_string(conn_str)
        import os
        env_conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if env_conn_str:
            return BlobServiceClient.from_connection_string(env_conn_str)
        account_url = params.get("account_url")
        if account_url:
            return BlobServiceClient(account_url=account_url)
        raise ValueError(
            "No Azure credentials found -- pass 'connection_string'/'account_url' "
            "or set AZURE_STORAGE_CONNECTION_STRING"
        )

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False,
        )
