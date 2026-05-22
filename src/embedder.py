"""
Component 3 — Embedding Generation & Vector Indexing.

Reads gold chunks, generates sentence-transformer embeddings,
builds a FAISS index, persists it to INDEX_DIR.

Mutation 1 (Self-Healing Idempotency): checks manifest before embedding.
Re-running is safe — already-embedded chunks are skipped.

python -m src.embedder
"""

import json
import os
import pickle
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv

load_dotenv()

GOLD_DIR = Path(os.environ.get("GOLD_DIR", "data/gold"))
INDEX_DIR = Path(os.environ.get("INDEX_DIR", "data/index"))
INDEX_DIR.mkdir(parents=True, exist_ok=True)

INDEX_PATH = INDEX_DIR / "fossilrag.faiss"
META_PATH = INDEX_DIR / "fossilrag_meta.pkl"

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


def load_model():
    from sentence_transformers import SentenceTransformer
    print(f"Loading embedding model: {MODEL_NAME}")
    return SentenceTransformer(MODEL_NAME)


def load_or_create_index() -> tuple[faiss.IndexFlatL2, list[dict]]:
    if INDEX_PATH.exists() and META_PATH.exists():
        print("Loading existing FAISS index...")
        index = faiss.read_index(str(INDEX_PATH))
        with open(META_PATH, "rb") as f:
            metadata = pickle.load(f)
        print(f"  Loaded {index.ntotal} vectors.")
        return index, metadata
    index = faiss.IndexFlatL2(EMBEDDING_DIM)
    return index, []


def save_index(index: faiss.IndexFlatL2, metadata: list[dict]):
    faiss.write_index(index, str(INDEX_PATH))
    with open(META_PATH, "wb") as f:
        pickle.dump(metadata, f)


def run():
    from src.manifest import content_hash, is_processed, mark_processed

    model = load_model()
    index, metadata = load_or_create_index()

    gold_files = [f for f in GOLD_DIR.glob("*_chunks.json")]
    if not gold_files:
        print(f"No chunk files in {GOLD_DIR}. Run src.chunker first.")
        return

    embedded = 0
    skipped = 0

    for gf in gold_files:
        chunks = json.loads(gf.read_text(encoding="utf-8"))
        for chunk in chunks:
            cid = chunk["chunk_id"]
            h = content_hash(chunk["text"])

            if is_processed(cid, h):
                skipped += 1
                continue

            vec = model.encode([chunk["text"]], normalize_embeddings=True)
            index.add(vec.astype(np.float32))
            metadata.append({
                "chunk_id": cid,
                "doc_id": chunk["doc_id"],
                "file_name": chunk["file_name"],
                "version": chunk["version"],
                "chunk_index": chunk["chunk_index"],
                "text": chunk["text"],
                "markers": chunk.get("markers", {}),
            })
            mark_processed(cid, chunk["doc_id"], h, chunk["version"])
            embedded += 1

    save_index(index, metadata)
    print(f"\nEmbedding complete.")
    print(f"  Embedded: {embedded}  |  Skipped (already indexed): {skipped}")
    print(f"  Index total: {index.ntotal} vectors")
    print(f"  Saved to: {INDEX_PATH}")


if __name__ == "__main__":
    run()
