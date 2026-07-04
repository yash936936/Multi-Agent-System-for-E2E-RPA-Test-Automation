from unittest.mock import patch, MagicMock

from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from agents.capability.azure_adapter import AzureBlobAdapter
from agents.capability.gcp_adapter import GcpStorageAdapter
from agents.capability.sharepoint_adapter import SharePointAdapter
from agents.capability.chatops_adapter import ChatOpsAdapter


# --- Azure Blob Adapter ---

def test_azure_adapter_blob_exists_success():
    adapter = AzureBlobAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AZURE_BLOB, target="report.pdf",
        params={"connection_string": "fake", "container": "docs", "blob_name": "report.pdf"},
        expected={"exists": True, "min_size_bytes": 100},
    )
    with patch("agents.capability.azure_adapter.BlobServiceClient.from_connection_string") as mock_from_conn:
        mock_blob_client = MagicMock()
        mock_props = MagicMock(size=500, last_modified="2024-01-01")
        mock_blob_client.get_blob_properties.return_value = mock_props
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob_client
        mock_from_conn.return_value = mock_service

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500


def test_azure_adapter_upload_blob_real_write():
    adapter = AzureBlobAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AZURE_BLOB, target="new.txt",
        params={
            "connection_string": "fake", "container": "docs", "blob_name": "new.txt",
            "action": "upload_blob", "content": "hello world",
        },
        expected={},
    )
    with patch("agents.capability.azure_adapter.BlobServiceClient.from_connection_string") as mock_from_conn:
        mock_blob_client = MagicMock()
        mock_blob_client.get_blob_properties.return_value = MagicMock(size=11)
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob_client
        mock_from_conn.return_value = mock_service

        result = adapter.run(payload)
        assert result.passed is True
        mock_blob_client.upload_blob.assert_called_once()
        assert result.evidence["uploaded_bytes"] == 11


def test_azure_adapter_missing_params():
    adapter = AzureBlobAdapter()
    payload = CapabilityCheckInput(capability=CapabilityType.AZURE_BLOB, target="", params={}, expected={})
    result = adapter.run(payload)
    assert result.passed is False
    assert "error" in result.evidence


# --- GCP Storage Adapter ---

def test_gcp_adapter_blob_exists_success():
    adapter = GcpStorageAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.GCP_STORAGE, target="report.pdf",
        params={"bucket": "my-bucket", "blob_name": "report.pdf"},
        expected={"exists": True, "min_size_bytes": 100},
    )
    with patch("agents.capability.gcp_adapter.storage.Client") as mock_client_cls:
        mock_blob = MagicMock(size=500, updated="2024-01-01")
        mock_blob.exists.return_value = True
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_client_cls.return_value = mock_client

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500


def test_gcp_adapter_upload_blob_real_write():
    adapter = GcpStorageAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.GCP_STORAGE, target="new.txt",
        params={"bucket": "my-bucket", "blob_name": "new.txt", "action": "upload_blob", "content": "hi"},
        expected={},
    )
    with patch("agents.capability.gcp_adapter.storage.Client") as mock_client_cls:
        mock_blob = MagicMock(size=2)
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_client_cls.return_value = mock_client

        result = adapter.run(payload)
        assert result.passed is True
        mock_blob.upload_from_string.assert_called_once()


# --- SharePoint Adapter ---

def test_sharepoint_adapter_file_exists_success():
    adapter = SharePointAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.SHAREPOINT, target="Shared Documents/report.pdf",
        params={
            "tenant_id": "t", "client_id": "c", "client_secret": "s",
            "drive_id": "drive123", "file_path": "Shared Documents/report.pdf",
        },
        expected={"exists": True},
    )
    with patch("agents.capability.sharepoint_adapter.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "fake-token"}
        token_resp.raise_for_status.return_value = None

        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {"size": 500, "lastModifiedDateTime": "2024-01-01"}
        meta_resp.raise_for_status.return_value = None

        mock_client.post.return_value = token_resp
        mock_client.get.return_value = meta_resp

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500


def test_sharepoint_adapter_missing_credentials():
    adapter = SharePointAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.SHAREPOINT, target="x",
        params={"drive_id": "d", "file_path": "x.txt"},
        expected={},
    )
    import os
    for var in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        os.environ.pop(var, None)
    result = adapter.run(payload)
    assert result.passed is False
    assert "auth error" in result.evidence["error"].lower()


# --- ChatOps Adapter ---

def test_chatops_adapter_slack_success():
    adapter = ChatOpsAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CHAT_OPS, target="",
        params={"platform": "slack", "webhook_url": "https://hooks.slack.com/x", "title": "AURA", "message": "Run passed"},
        expected={},
    )
    with patch("agents.capability.chatops_adapter.httpx.Client") as mock_client_cls:
        mock_response = MagicMock(status_code=200)
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_response

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["platform"] == "slack"


def test_chatops_adapter_teams_success():
    adapter = ChatOpsAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CHAT_OPS, target="",
        params={
            "platform": "teams", "webhook_url": "https://outlook.office.com/x",
            "title": "AURA", "message": "Run failed", "fields": [{"title": "Run ID", "value": "abc123"}],
        },
        expected={},
    )
    with patch("agents.capability.chatops_adapter.httpx.Client") as mock_client_cls:
        mock_response = MagicMock(status_code=200)
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_post = mock_client_cls.return_value.__enter__.return_value.post
        mock_post.return_value = mock_response

        result = adapter.run(payload)
        assert result.passed is True
        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_body["@type"] == "MessageCard"
        assert sent_body["sections"][0]["facts"][0]["name"] == "Run ID"


def test_chatops_adapter_missing_webhook():
    adapter = ChatOpsAdapter()
    payload = CapabilityCheckInput(capability=CapabilityType.CHAT_OPS, target="", params={}, expected={})
    result = adapter.run(payload)
    assert result.passed is False
