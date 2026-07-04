from google.api_core.exceptions import NotFound, GoogleAPIError
from google.cloud import storage
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class GcpStorageAdapter:
    """
    Phase 16b: Validates and manipulates Google Cloud Storage.

    Mirrors AzureBlobAdapter's shape (same action vocabulary: blob_exists /
    upload_blob / download_blob / list_blobs) so a spec author moving a
    test between clouds only changes capability_type, not the mental
    model. Real read/write, not detect-only.

    Auth: params["credentials_path"] (service-account JSON path), or
    falls back to Application Default Credentials (GOOGLE_APPLICATION_
    CREDENTIALS env var / attached service account) via
    storage.Client() with no explicit credentials.
    """

    capability_type: CapabilityType = CapabilityType.GCP_STORAGE

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        action = params.get("action", "blob_exists")

        bucket_name = params.get("bucket")
        blob_name = params.get("blob_name")
        if not all([bucket_name, blob_name]):
            return self._fail("Missing 'bucket' or 'blob_name'")

        try:
            client = self._client(params)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            if action == "upload_blob":
                content = params.get("content", "")
                data = content.encode("utf-8") if isinstance(content, str) else content
                blob.upload_from_string(data)
                blob.reload()
                evidence = {
                    "bucket": bucket_name, "blob_name": blob_name,
                    "action": action, "uploaded_bytes": blob.size,
                }
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=True, confidence=1.0,
                    evidence=evidence, escalate=False,
                )

            if action == "list_blobs":
                prefix = params.get("prefix", "")
                names = [b.name for b in client.list_blobs(bucket_name, prefix=prefix)]
                passed = True
                evidence = {"bucket": bucket_name, "prefix": prefix, "blob_names": names, "count": len(names)}
                if expected.get("min_count") is not None and len(names) < expected["min_count"]:
                    passed = False
                    evidence["count_mismatch"] = True
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=passed,
                    confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
                )

            if action == "download_blob":
                if not blob.exists():
                    raise NotFound(f"{bucket_name}/{blob_name}")
                text = blob.download_as_text(encoding="utf-8")
                evidence = {"bucket": bucket_name, "blob_name": blob_name, "size_bytes": len(text.encode("utf-8"))}
                passed = True
                if expected.get("content_contains") and expected["content_contains"] not in text:
                    passed = False
                    evidence["missing_expected_content"] = True
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=passed,
                    confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
                )

            # default: blob_exists (detect-only)
            if not blob.exists():
                raise NotFound(f"{bucket_name}/{blob_name}")
            blob.reload()
            evidence = {
                "bucket": bucket_name, "blob_name": blob_name, "exists": True,
                "size_bytes": blob.size, "updated": str(blob.updated),
            }
            passed = True
            if expected.get("exists") is False:
                passed = False
                evidence["unexpected_existence"] = True
            if expected.get("min_size_bytes") and blob.size < expected["min_size_bytes"]:
                passed = False
                evidence["size_mismatch"] = True
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed,
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
            )

        except NotFound:
            passed = expected.get("exists") is False
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, confidence=1.0,
                evidence={"bucket": bucket_name, "blob_name": blob_name, "exists": False}, escalate=False,
            )
        except GoogleAPIError as e:
            return self._fail(f"GCP API error: {str(e)}")
        except Exception as e:
            return self._fail(f"GCP execution error: {str(e)}")

    @staticmethod
    def _client(params: dict) -> "storage.Client":
        creds_path = params.get("credentials_path")
        if creds_path:
            return storage.Client.from_service_account_json(creds_path)
        project = params.get("project")
        return storage.Client(project=project) if project else storage.Client()

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False,
        )
