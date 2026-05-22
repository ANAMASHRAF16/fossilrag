"""
Lambda 3 — FastAPI via Mangum.

On cold start: downloads all gold chunk files from S3, builds FAISS
index in memory. Warm invocations reuse the index — no S3 reads.

Handler: api_handler.handler
Function URL: enabled (Auth: NONE for demo)
"""

import json
import os
import pickle
import tempfile

import boto3
import faiss
import numpy as np
from mangum import Mangum

GOLD_BUCKET = os.environ["GOLD_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")

s3 = boto3.client("s3", region_name=AWS_REGION)

# ── Build FAISS index from gold S3 chunks (runs once on cold start) ───────────

EMBEDDING_DIM = 384
_index = None
_metadata = []
_model = None


def load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def build_index():
    global _index, _metadata
    print("Building FAISS index from gold S3...")

    index = faiss.IndexFlatL2(EMBEDDING_DIM)
    metadata = []

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=GOLD_BUCKET, Prefix="gold/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            body = s3.get_object(Bucket=GOLD_BUCKET, Key=key)["Body"].read()
            chunk = json.loads(body)
            vec = np.array(chunk["embedding"], dtype=np.float32).reshape(1, -1)
            index.add(vec)
            metadata.append({k: v for k, v in chunk.items() if k != "embedding"})

    _index = index
    _metadata = metadata
    print(f"Index ready: {index.ntotal} vectors from {GOLD_BUCKET}")


# Build index on cold start
build_index()
load_model()

# ── Patch app state so src/api/main.py endpoints work ────────────────────────

from src.api.main import app

app.state.index = _index
app.state.metadata = _metadata
app.state.model = _model

handler = Mangum(app, lifespan="off")
