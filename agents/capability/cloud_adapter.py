import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class CloudAdapter:
    """
    Phase 16: Validates Cloud resources (AWS S3 focus).
    Detect-only: Does not create, modify, or delete cloud resources.
    """
    capability_type: CapabilityType = CapabilityType.CLOUD

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        action = params.get("action", "s3_object_exists")
        if action != "s3_object_exists":
            # Only s3_object_exists is implemented so far -- previously
            # `action` was read but never checked, so any other value
            # (e.g. a typo, or a not-yet-implemented action) silently ran
            # the s3_object_exists path anyway instead of failing loudly.
            return self._fail(
                f"Unsupported cloud action '{action}'. Supported actions: s3_object_exists"
            )

        bucket = params.get("bucket")
        key = params.get("key")
        
        if not all([bucket, key]):
            return self._fail("Missing 'bucket' or 'key'")
            
        try:
            # Debug Fix: Only pass credentials if explicitly provided. 
            # This allows fallback to IAM roles, ~/.aws/credentials, or env vars.
            boto_kwargs = {"region_name": params.get("region_name", "us-east-1")}
            if params.get("aws_access_key_id"):
                boto_kwargs["aws_access_key_id"] = params["aws_access_key_id"]
            if params.get("aws_secret_access_key"):
                boto_kwargs["aws_secret_access_key"] = params["aws_secret_access_key"]
                
            s3 = boto3.client('s3', **boto_kwargs)
            
            response = s3.head_object(Bucket=bucket, Key=key)
            evidence = {
                "bucket": bucket,
                "key": key,
                "exists": True,
                "size_bytes": response['ContentLength'],
                "last_modified": str(response['LastModified'])
            }
            passed = True
            
            if expected.get("exists") is False:
                passed = False
                evidence["unexpected_existence"] = True
                
            if expected.get("min_size_bytes") and response['ContentLength'] < expected["min_size_bytes"]:
                passed = False
                evidence["size_mismatch"] = True
                
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            # S3 returns '404' or 'NoSuchKey' for missing objects
            if error_code in ['404', 'NoSuchKey']:
                passed = expected.get("exists") is False
                return CapabilityCheckResult(
                    capability=self.capability_type, passed=passed, confidence=1.0,
                    evidence={"bucket": bucket, "key": key, "exists": False}, escalate=False
                )
            return self._fail(f"AWS ClientError: {error_code} - {e.response['Error']['Message']}")
        except NoCredentialsError:
            return self._fail("AWS credentials not provided or invalid")
        except Exception as e:
            return self._fail(f"Cloud execution error: {str(e)}")

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False
        )