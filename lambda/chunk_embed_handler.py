"""
Lambda 2 — Chunking + Embedding.

Triggered by SQS (which receives S3 ObjectCreated events from silver bucket).
Reads silver JSON, chunks text, generates embeddings, writes to gold bucket.

Mutation 1 (Self-Healing Idempotency): checks DynamoDB manifest before
embedding. Re-runs and retries are safe.

Mutation 2 (Auto-Scaling Lambda with DLQ): ReservedConcurrentExecutions=5
caps DynamoDB pressure. Failed batches route to DLQ after 3 attempts.
Returns ReportBatchItemFailures so only failed messages are redriven.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

SILVER_BUCKET = os.environ["SILVER_BUCKET"]
GOLD_BUCKET = os.environ["GOLD_BUCKET"]
MANIFEST_TABLE = os.environ.get("MANIFEST_TABLE", "fossilrag-manifest")
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")

s3 = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(MANIFEST_TABLE)

MIN_CHUNK = 50
MAX_CHUNK = 1000

# Load model once at cold start — reused across warm invocations
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print("Model loaded.")
    return _model


# ── Text cleaning + chunking ──────────────────────────────────────────────────

def clean(text):
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_chunks(text):
    chunks = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if len(para) >= MIN_CHUNK:
            chunks.append(para[:MAX_CHUNK])
    return chunks


def chunk_id(doc_id, index, text):
    return hashlib.sha256(f"{doc_id}::{index}::{text[:64]}".encode()).hexdigest()[:20]


def content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


# ── Idempotency (Mutation 1) ──────────────────────────────────────────────────

def is_processed(cid, h):
    try:
        resp = table.get_item(Key={"chunk_id": cid})
        item = resp.get("Item")
        return item is not None and item.get("text_hash") == h
    except ClientError:
        return False


def mark_processed(cid, doc_id, h, version):
    table.put_item(Item={
        "chunk_id": cid,
        "doc_id": doc_id,
        "text_hash": h,
        "version": version,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })


# ── Lambda handler ────────────────────────────────────────────────────────────

def handler(event, context):
    failed_ids = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            # S3 event notification wrapped in SQS body
            s3_records = body.get("Records", [])
            for s3_rec in s3_records:
                silver_key = s3_rec["s3"]["object"]["key"]
                process_silver_key(silver_key)
        except Exception as e:
            print(f"FAILED {message_id}: {e}")
            failed_ids.append(message_id)

    # Mutation 2: partial batch response — only failed messages are redriven
    return {
        "batchItemFailures": [{"itemIdentifier": mid} for mid in failed_ids]
    }


def process_silver_key(silver_key):
    obj = s3.get_object(Bucket=SILVER_BUCKET, Key=silver_key)
    rec = json.loads(obj["Body"].read())

    text = clean(rec["text"])
    paragraphs = split_chunks(text)
    model = get_model()
    embedded = skipped = 0

    for i, para in enumerate(paragraphs):
        cid = chunk_id(rec["doc_id"], i, para)
        h = content_hash(para)

        if is_processed(cid, h):
            skipped += 1
            continue

        vec = model.encode([para], normalize_embeddings=True)[0].tolist()
        chunk = {
            "chunk_id": cid,
            "doc_id": rec["doc_id"],
            "file_name": rec["file_name"],
            "version": rec["version"],
            "chunk_index": i,
            "text": para,
            "markers": rec.get("markers", {}),
            "embedding": vec,
        }

        gold_key = f"gold/{cid}.json"
        s3.put_object(
            Bucket=GOLD_BUCKET,
            Key=gold_key,
            Body=json.dumps(chunk).encode(),
            ContentType="application/json",
        )
        mark_processed(cid, rec["doc_id"], h, rec["version"])
        embedded += 1

    print(f"{silver_key}: embedded={embedded}, skipped={skipped}")
