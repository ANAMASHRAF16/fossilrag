"""
Validation for Component 3 — Embedding Generation + Vector Indexing.

This test runs the actual sentence-transformers model, so it's slower
than the other test suites (~5-10s including model warmup). CI caches
the HuggingFace model dir so subsequent runs are fast.

7 checks covering model dim, FAISS index build, idempotency via the
manifest (Mutation 1), persistence, and the embedded->indexed flow.

Run:
    python tests/test_embedder.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["MANIFEST_BACKEND"] = "local"

ROOT = Path(__file__).parent.parent
INDEX_DIR = ROOT / "data" / "index"
GOLD_DIR = ROOT / "data" / "gold"

sys.path.insert(0, str(ROOT))


def setup():
    """Ensure gold chunks exist; clear index for deterministic run."""
    if INDEX_DIR.exists():
        shutil.rmtree(INDEX_DIR)
    from src.manifest import clear_all
    clear_all()
    if not GOLD_DIR.exists() or not list(GOLD_DIR.glob("*_chunks.json")):
        # Build silver + gold from samples
        subprocess.run([sys.executable, str(ROOT / "tests" / "generate_samples.py")], check=True)
        subprocess.run([sys.executable, "-m", "src.extractor"], cwd=str(ROOT), check=True)
        subprocess.run([sys.executable, "-m", "src.chunker"], cwd=str(ROOT), check=True)


def check_embedding_dim_matches_model() -> bool:
    print("[1/7] embedding dim is 384 (all-MiniLM-L6-v2)...")
    from src.embedder import EMBEDDING_DIM, load_model
    model = load_model()
    vec = model.encode(["test sentence"], normalize_embeddings=True)
    if vec.shape[1] != EMBEDDING_DIM:
        print(f"  FAIL: model dim {vec.shape[1]} != configured EMBEDDING_DIM {EMBEDDING_DIM}")
        return False
    print(f"  OK: dim = {EMBEDDING_DIM}, matches model output")
    return True


def check_first_embedder_run_writes_index() -> bool:
    print("[2/7] first embedder run builds and persists FAISS index...")
    result = subprocess.run(
        [sys.executable, "-m", "src.embedder"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"  FAIL: embedder exited {result.returncode}\n  stderr: {result.stderr}")
        return False
    if not (INDEX_DIR / "fossilrag.faiss").exists():
        print("  FAIL: fossilrag.faiss not written")
        return False
    if not (INDEX_DIR / "fossilrag_meta.pkl").exists():
        print("  FAIL: fossilrag_meta.pkl not written")
        return False
    print(f"  OK: FAISS index + metadata persisted")
    return True


def check_index_contains_all_chunks() -> bool:
    print("[3/7] FAISS vector count matches total gold chunks...")
    import faiss, json
    index = faiss.read_index(str(INDEX_DIR / "fossilrag.faiss"))
    total_chunks = 0
    for gf in GOLD_DIR.glob("*_chunks.json"):
        total_chunks += len(json.loads(gf.read_text(encoding="utf-8")))
    if index.ntotal != total_chunks:
        print(f"  FAIL: index has {index.ntotal} vectors, expected {total_chunks}")
        return False
    print(f"  OK: index.ntotal = {index.ntotal} = total gold chunks")
    return True


def check_metadata_aligned_with_vectors() -> bool:
    print("[4/7] metadata list length equals FAISS index size...")
    import faiss, pickle
    index = faiss.read_index(str(INDEX_DIR / "fossilrag.faiss"))
    with open(INDEX_DIR / "fossilrag_meta.pkl", "rb") as f:
        meta = pickle.load(f)
    if len(meta) != index.ntotal:
        print(f"  FAIL: meta has {len(meta)} entries, index has {index.ntotal}")
        return False
    print(f"  OK: {len(meta)} metadata entries, one per vector")
    return True


def check_second_run_skips_via_manifest() -> bool:
    print("[5/7] second embedder run skips all chunks via manifest...")
    result = subprocess.run(
        [sys.executable, "-m", "src.embedder"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"  FAIL: second run failed")
        return False
    out = result.stdout
    if "Embedded: 0" not in out:
        print(f"  FAIL: second run embedded chunks instead of skipping. Output:\n{out}")
        return False
    if "Skipped" not in out:
        print(f"  FAIL: no skip count in output")
        return False
    print(f"  OK: second run reports 'Embedded: 0' - Mutation 1 working")
    return True


def check_index_size_stable_on_re_run() -> bool:
    print("[6/7] FAISS index size unchanged after re-run (no duplicates)...")
    import faiss
    index = faiss.read_index(str(INDEX_DIR / "fossilrag.faiss"))
    before = index.ntotal
    subprocess.run([sys.executable, "-m", "src.embedder"], cwd=str(ROOT), capture_output=True)
    index2 = faiss.read_index(str(INDEX_DIR / "fossilrag.faiss"))
    if index2.ntotal != before:
        print(f"  FAIL: vector count changed {before} -> {index2.ntotal}")
        return False
    print(f"  OK: vector count stable at {before} across re-runs")
    return True


def check_similarity_search_returns_relevant_chunk() -> bool:
    print("[7/7] similarity search retrieves a chunk containing the query term...")
    import faiss, pickle
    import numpy as np
    from src.embedder import load_model
    index = faiss.read_index(str(INDEX_DIR / "fossilrag.faiss"))
    with open(INDEX_DIR / "fossilrag_meta.pkl", "rb") as f:
        meta = pickle.load(f)
    model = load_model()
    q = model.encode(["error code"], normalize_embeddings=True).astype(np.float32)
    _, indices = index.search(q, 3)
    top_texts = [meta[i]["text"].lower() for i in indices[0] if i >= 0]
    if not any("err" in t or "error" in t for t in top_texts):
        print(f"  FAIL: top-3 results don't contain error-related text")
        return False
    print(f"  OK: top-3 results include error-related chunks")
    return True


def main():
    print("=" * 60)
    print("FossilRAG - PR 3 embedder + idempotency validation")
    print("=" * 60)
    setup()
    checks = [
        check_embedding_dim_matches_model,
        check_first_embedder_run_writes_index,
        check_index_contains_all_chunks,
        check_metadata_aligned_with_vectors,
        check_second_run_skips_via_manifest,
        check_index_size_stable_on_re_run,
        check_similarity_search_returns_relevant_chunk,
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
