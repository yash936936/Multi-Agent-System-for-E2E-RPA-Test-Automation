import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

# 2026-07-13 (decisions.md D-017 / roadmap issue 1.5): `action` used to be
# read but never branched on -- any value silently ran the
# s3_object_exists path. Fixed by rejecting unrecognized actions
# explicitly (already done in a prior pass) and, in this pass, adding
# `list_objects` as a second real action -- deliberately DETECT-ONLY,
# matching this adapter's documented design contract (TRD.md §9:
# "cloud_adapter default[s] to read/detect-only operations rather than
# mutating the systems they check"). `upload_object`/`delete_object`/
# `download_object` are intentionally NOT implemented here even though an
# earlier planning note suggested them -- adding write/delete actions to a
# detect-only validation adapter would be a real design regression, not a
# bug fix. If mutating S3 operations are ever genuinely needed, they
# belong in a separate, clearly-labeled adapter (e.g. a future
# `cloud_setup_adapter`), not folded into the one every test spec already
# trusts to be side-effect-free.
_SUPPORTED_ACTIONS = ("s3_object_exists", "list_objects")


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
        if action not in _SUPPORTED_ACTIONS:
            return self._fail(
                f"Unsupported cloud action '{action}'. Supported actions: "
                f"{', '.join(_SUPPORTED_ACTIONS)} (detect-only by design -- "
                f"see TRD.md §9)"
            )

        if action == "list_objects":
            return self._list_objects(params, expected)

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

    def _list_objects(self, params, expected) -> CapabilityCheckResult:
        """
        Detect-only: lists object keys under an optional prefix and checks
        the count/presence against `expected`. Useful for validating "did a
        deployment/export land the files we expect" without ever writing.
        """
        bucket = params.get("bucket")
        if not bucket:
            return self._fail("Missing 'bucket'")

        prefix = params.get("prefix", "")
        try:
            boto_kwargs = {"region_name": params.get("region_name", "us-east-1")}
            if params.get("aws_access_key_id"):
                boto_kwargs["aws_access_key_id"] = params["aws_access_key_id"]
            if params.get("aws_secret_access_key"):
                boto_kwargs["aws_secret_access_key"] = params["aws_secret_access_key"]

            s3 = boto3.client('s3', **boto_kwargs)
            response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            keys = [obj["Key"] for obj in response.get("Contents", [])]

            evidence = {"bucket": bucket, "prefix": prefix, "object_count": len(keys), "keys": keys}
            passed = True

            min_count = expected.get("min_count")
            if min_count is not None and len(keys) < min_count:
                passed = False
                evidence["count_below_minimum"] = True

            must_contain = expected.get("must_contain_key")
            if must_contain is not None:
                found = must_contain in keys
                evidence["required_key_found"] = found
                if not found:
                    passed = False

            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed,
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        except ClientError as e:
            error_code = e.response['Error']['Code']
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