import pytest
from unittest.mock import patch, MagicMock
from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from agents.capability.cloud_adapter import CloudAdapter
from agents.capability.workflow_adapter import WorkflowAdapter
from botocore.exceptions import ClientError

# --- Cloud Adapter Tests ---
def test_cloud_adapter_s3_exists_success():
    adapter = CloudAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CLOUD, target="s3://my-bucket/report.pdf",
        params={
            "action": "s3_object_exists", 
            "bucket": "my-bucket", 
            "key": "report.pdf",
            "aws_access_key_id": "test", 
            "aws_secret_access_key": "test"
        },
        expected={"exists": True, "min_size_bytes": 100}
    )
    
    with patch("agents.capability.cloud_adapter.boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.head_object.return_value = {
            'ContentLength': 500,
            'LastModified': "2024-01-01T00:00:00Z"
        }
        
        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500

def test_cloud_adapter_s3_not_found():
    adapter = CloudAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CLOUD, target="",
        params={"bucket": "b", "key": "k", "aws_access_key_id": "t", "aws_secret_access_key": "t"},
        expected={"exists": False} # We expect it to be missing
    )
    
    with patch("agents.capability.cloud_adapter.boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        
        # Simulate boto3 404 error
        error_response = {'Error': {'Code': '404', 'Message': 'Not Found'}}
        mock_s3.head_object.side_effect = ClientError(error_response, 'HeadObject')
        
        result = adapter.run(payload)
        assert result.passed is True # Passed because we expected it to be missing
        assert result.evidence["exists"] is False

# --- Workflow Adapter Tests ---
def test_workflow_adapter_trigger_success():
    adapter = WorkflowAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WORKFLOW, target="https://jenkins/job/build",
        params={"url": "https://jenkins/job/build", "payload": {"ref": "main"}},
        expected={"accepted_status_codes": [200, 201]}
    )
    
    with patch("httpx.Client") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_client.return_value.__enter__.return_value.post.return_value = mock_response
        
        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["status_code"] == 201

def test_workflow_adapter_trigger_rejected():
    adapter = WorkflowAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WORKFLOW, target="",
        params={"url": "https://jenkins/job/build"},
        expected={}
    )
    
    with patch("httpx.Client") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 403 # Forbidden
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_client.return_value.__enter__.return_value.post.return_value = mock_response
        
        result = adapter.run(payload)
        assert result.passed is False