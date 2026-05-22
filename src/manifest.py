"""
Mutation 1 — Self-Healing Idempotency.

Tracks processed chunk_ids so re-runs skip already-embedded chunks.
Two backends:
  local     — JSON file (Phase 1, no AWS)
  dynamodb  — DynamoDB table (Phase 2)

Same interface as Activity 8 embedding-idempotency.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND = os.environ.get("MANIFEST_BACKEND", "local")
LOCAL_MANIFEST = Path(os.environ.get("GOLD_DIR", "data/gold")) / "manifest.json"
TABLE_NAME = os.environ.get("MANIFEST_TABLE", "fossilrag-manifest")
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")


def _load_local() -> dict:
    if LOCAL_MANIFEST.exists():
        return json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8"))
    return {}


def _save_local(manifest: dict):
    LOCAL_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _dynamo_table():
    import boto3
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def is_processed(chunk_id: str, text_hash: str) -> bool:
    if BACKEND == "local":
        m = _load_local()
        item = m.get(chunk_id)
        return item is not None and item.get("text_hash") == text_hash
    else:
        from botocore.exceptions import ClientError
        try:
            resp = _dynamo_table().get_item(Key={"chunk_id": chunk_id})
            item = resp.get("Item")
            return item is not None and item.get("text_hash") == text_hash
        except ClientError:
            return False


def mark_processed(chunk_id: str, doc_id: str, text_hash: str, version: int):
    entry = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text_hash": text_hash,
        "version": version,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    if BACKEND == "local":
        m = _load_local()
        m[chunk_id] = entry
        _save_local(m)
    else:
        _dynamo_table().put_item(Item=entry)


def clear_all():
    """For testing — wipe the manifest."""
    if BACKEND == "local":
        if LOCAL_MANIFEST.exists():
            LOCAL_MANIFEST.unlink()
    else:
        table = _dynamo_table()
        scan = table.scan(ProjectionExpression="chunk_id")
        with table.batch_writer() as batch:
            for item in scan.get("Items", []):
                batch.delete_item(Key={"chunk_id": item["chunk_id"]})
