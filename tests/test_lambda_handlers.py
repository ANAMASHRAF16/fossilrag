"""
Validation for Lambda handler modules — structural and behavioral
checks that don't require a live AWS account.

For chunk_embed_handler we verify the partial-batch-response contract
that Mutation 2 depends on: when one message fails inside a batch,
the handler must return `batchItemFailures: [{itemIdentifier: ...}]`
listing only the failed messageId, so SQS redrives only that one and
the rest of the batch is considered processed.

We test this with monkeypatched S3 + DynamoDB clients (no boto3 calls
hit real AWS) so the suite runs in CI without credentials.

Run:
    python tests/test_lambda_handlers.py
"""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Set env vars BEFORE importing the handlers (they read at import time)
os.environ["RAW_BUCKET"] = "fossilrag-raw-test"
os.environ["SILVER_BUCKET"] = "fossilrag-silver-test"
os.environ["GOLD_BUCKET"] = "fossilrag-gold-test"
os.environ["MANIFEST_TABLE"] = "fossilrag-manifest-test"
os.environ["AWS_REGION"] = "us-east-1"

ROOT = Path(__file__).parent.parent
# "lambda" is a Python reserved word so we can't use it as a package name.
# Add the lambda directory itself to sys.path so the handlers import flat.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lambda"))


def check_extract_handler_imports() -> bool:
    print("[1/6] lambda.extract_handler module imports cleanly...")
    try:
        with patch("boto3.client", return_value=MagicMock()):
            mod = importlib.import_module("extract_handler")
            assert hasattr(mod, "handler"), "missing handler function"
            assert hasattr(mod, "EXTRACTORS"), "missing EXTRACTORS dispatch"
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return False
    print("  OK: extract_handler imports, exposes handler + EXTRACTORS")
    return True


def check_chunk_embed_handler_imports() -> bool:
    print("[2/6] lambda.chunk_embed_handler module imports cleanly...")
    try:
        with patch("boto3.client", return_value=MagicMock()), \
             patch("boto3.resource", return_value=MagicMock()):
            mod = importlib.import_module("chunk_embed_handler")
            assert hasattr(mod, "handler"), "missing handler function"
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return False
    print("  OK: chunk_embed_handler imports, exposes handler")
    return True


def check_partial_batch_response_on_failure() -> bool:
    """Mutation 2: failed messages are returned individually, not as whole-batch fail."""
    print("[3/6] Mutation 2: handler returns batchItemFailures for failed msgs...")
    with patch("boto3.client", return_value=MagicMock()), \
         patch("boto3.resource", return_value=MagicMock()):
        # Reimport to get a fresh module with mocked boto3
        if "chunk_embed_handler" in sys.modules:
            del sys.modules["chunk_embed_handler"]
        mod = importlib.import_module("chunk_embed_handler")

        # Construct an event where one of two SQS messages will fail because
        # its body is not valid JSON. The other has well-formed JSON but
        # references a silver key the mocked S3 won't return — both will fail
        # in process_silver_key, but we patch process_silver_key on one to
        # succeed.
        def fake_process(key):
            if "good" in key:
                return  # success
            raise RuntimeError("simulated extraction error")

        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": '{"Records":[{"s3":{"object":{"key":"good.json"}}}]}',
                },
                {
                    "messageId": "msg-2",
                    "body": '{"Records":[{"s3":{"object":{"key":"bad.json"}}}]}',
                },
            ]
        }

        with patch.object(mod, "process_silver_key", side_effect=fake_process):
            result = mod.handler(event, None)

    if "batchItemFailures" not in result:
        print(f"  FAIL: response missing batchItemFailures key: {result}")
        return False
    failures = result["batchItemFailures"]
    if len(failures) != 1:
        print(f"  FAIL: expected exactly 1 failed message, got {len(failures)}")
        return False
    if failures[0]["itemIdentifier"] != "msg-2":
        print(f"  FAIL: expected msg-2 in failures, got {failures[0]}")
        return False
    print("  OK: failed msg-2 reported as batchItemFailure, msg-1 not redriven")
    return True


def check_handler_returns_empty_failures_on_success() -> bool:
    """All messages succeed => batchItemFailures should be empty."""
    print("[4/6] handler returns empty batchItemFailures when all succeed...")
    with patch("boto3.client", return_value=MagicMock()), \
         patch("boto3.resource", return_value=MagicMock()):
        if "chunk_embed_handler" in sys.modules:
            del sys.modules["chunk_embed_handler"]
        mod = importlib.import_module("chunk_embed_handler")

        event = {
            "Records": [
                {"messageId": "msg-a", "body": '{"Records":[{"s3":{"object":{"key":"a.json"}}}]}'},
                {"messageId": "msg-b", "body": '{"Records":[{"s3":{"object":{"key":"b.json"}}}]}'},
            ]
        }

        with patch.object(mod, "process_silver_key", return_value=None):
            result = mod.handler(event, None)

    if result.get("batchItemFailures") != []:
        print(f"  FAIL: expected empty batchItemFailures, got {result}")
        return False
    print("  OK: all-success batch returns []")
    return True


def check_extract_skips_unsupported() -> bool:
    print("[5/6] extract_handler skips unsupported file extensions...")
    with patch("boto3.client") as boto:
        s3_client = MagicMock()
        boto.return_value = s3_client
        if "extract_handler" in sys.modules:
            del sys.modules["extract_handler"]
        mod = importlib.import_module("extract_handler")

        event = {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": "fossilrag-raw-test"},
                        "object": {"key": "weird.xyz"},
                    }
                }
            ]
        }
        result = mod.handler(event, None)
        if s3_client.get_object.called:
            print("  FAIL: extract attempted to get_object on unsupported file")
            return False
        if result.get("statusCode") != 200:
            print(f"  FAIL: unexpected status {result.get('statusCode')}")
            return False
    print("  OK: unsupported file types skipped without S3 read")
    return True


def check_dockerfile_uses_lambda_base_image() -> bool:
    print("[6/6] Dockerfile uses an AWS Lambda Python base image...")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    if "public.ecr.aws/lambda/python" not in dockerfile:
        print("  FAIL: Dockerfile does not use the AWS Lambda Python base image")
        return False
    if "sentence-transformers" not in dockerfile and "SentenceTransformer" not in dockerfile:
        print("  FAIL: Dockerfile does not pre-install/cache sentence-transformers model")
        return False
    print("  OK: Lambda base image + model pre-bake present")
    return True


def main():
    print("=" * 60)
    print("FossilRAG - PR 5 Lambda handlers + Mutation 2 contract validation")
    print("=" * 60)
    checks = [
        check_extract_handler_imports,
        check_chunk_embed_handler_imports,
        check_partial_batch_response_on_failure,
        check_handler_returns_empty_failures_on_success,
        check_extract_skips_unsupported,
        check_dockerfile_uses_lambda_base_image,
    ]
    results = [c() for c in checks]
    print("=" * 60)
    if all(results):
        print(f"PASS - {sum(results)}/{len(results)} checks succeeded")
        sys.exit(0)
    print(f"FAIL - {sum(results)}/{len(results)} checks succeeded")
    sys.exit(1)


if __name__ == "__main__":
    main()
