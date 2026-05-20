"""
Component 4 — Retrieval API (FastAPI).

Endpoints:
  GET  /health
  GET  /excavate          - top-k similarity search (+ time-travel via ?version=)
  POST /mutate            - structured enrichment summary via Gemini
  GET  /export/finetune   - download JSONL training dataset (Mutation 5)
  GET  /time-travel       - compare two versions of a document (Mutation 4)

Run locally:
  uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import pickle
from contextlib import asynccontextmanager
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

load_dotenv()

INDEX_DIR = Path(os.environ.get("INDEX_DIR", "data/index"))
INDEX_PATH = INDEX_DIR / "fossilrag.faiss"
META_PATH = INDEX_DIR / "fossilrag_meta.pkl"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not INDEX_PATH.exists():
        raise RuntimeError(
            f"FAISS index not found at {INDEX_PATH}. Run: python -m src.embedder"
        )
    app.state.index = faiss.read_index(str(INDEX_PATH))
    with open(META_PATH, "rb") as f:
        app.state.metadata = pickle.load(f)

    from sentence_transformers import SentenceTransformer
    app.state.model = SentenceTransformer("all-MiniLM-L6-v2")
    print(f"FossilRAG ready. {app.state.index.ntotal} vectors loaded.")
    yield


app = FastAPI(title="FossilRAG", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "vectors": app.state.index.ntotal,
        "docs": len({m["doc_id"] for m in app.state.metadata}),
    }


@app.get("/excavate")
async def excavate(
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    version: int | None = Query(None),
    doc_id: str | None = Query(None),
):
    """
    Embed the query, run top-k FAISS search, return relevant chunks.

    Mutation 4 (Time-Travel): pass ?version=N to filter to a specific document version.
    """
    vec = app.state.model.encode([q], normalize_embeddings=True).astype(np.float32)
    distances, indices = app.state.index.search(vec, min(top_k * 4, app.state.index.ntotal))

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or len(results) >= top_k:
            break
        meta = app.state.metadata[idx]
        if version is not None and meta["version"] != version:
            continue
        if doc_id is not None and meta["doc_id"] != doc_id:
            continue
        results.append({
            "chunk_id": meta["chunk_id"],
            "doc_id": meta["doc_id"],
            "file_name": meta["file_name"],
            "version": meta["version"],
            "chunk_index": meta["chunk_index"],
            "score": round(float(1 / (1 + dist)), 4),
            "text": meta["text"],
            "markers": meta.get("markers", {}),
        })

    return {
        "query": q,
        "version_filter": version,
        "returned": len(results),
        "results": results,
    }


@app.post("/mutate")
async def mutate(
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
):
    """
    Retrieve top-k chunks, build a prompt, call Gemini for enrichment summary.

    Mutation 3 (Prompt Fossilization): cache hit = instant response.
    Fallback: if Gemini fails, return structured marker aggregation.
    """
    from src.api.mutate_handler import generate_mutation
    return await generate_mutation(app, query, top_k)


@app.get("/export/finetune", response_class=PlainTextResponse)
async def export_finetune(doc_id: str | None = Query(None)):
    """
    Mutation 5 — Fine-Tuning Dataset Builder.
    Returns JSONL of instruction/input/output pairs from gold chunks.
    """
    from src.finetune_builder import export_jsonl
    jsonl = export_jsonl(doc_id)
    if not jsonl:
        raise HTTPException(status_code=404, detail="No chunks found to export.")
    return PlainTextResponse(content=jsonl, media_type="application/x-ndjson")


@app.get("/time-travel")
async def time_travel(
    doc_id: str = Query(...),
    from_version: int = Query(...),
    to_version: int = Query(...),
):
    """
    Mutation 4 — Time-Travel Query.
    Compare two versions of a document: new chunks, removed chunks, marker changes.
    """
    from src.time_travel import available_versions, compare_versions
    versions = available_versions(doc_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"No versions found for doc_id={doc_id}")
    if from_version not in versions or to_version not in versions:
        raise HTTPException(
            status_code=400,
            detail=f"Available versions for {doc_id}: {versions}",
        )
    return compare_versions(doc_id, from_version, to_version)
