"""
Validation for Component 2 — Text Cleaning & Semantic Chunking.

6 checks covering cleaning, splitting, deterministic IDs, edge cases,
and the contract between silver JSON and gold chunks.

Run:
    python tests/test_chunker.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SILVER_DIR = ROOT / "data" / "silver"
GOLD_DIR = ROOT / "data" / "gold"

sys.path.insert(0, str(ROOT))


def setup():
    """Run extractor first so silver files exist."""
    if GOLD_DIR.exists():
        shutil.rmtree(GOLD_DIR)
    if not SILVER_DIR.exists() or not list(SILVER_DIR.glob("*.json")):
        subprocess.run([sys.executable, str(ROOT / "tests" / "generate_samples.py")], check=True)
        subprocess.run([sys.executable, "-m", "src.extractor"], cwd=str(ROOT), check=True)


def check_clean_removes_control_chars() -> bool:
    print("[1/6] clean_text removes control chars and normalises whitespace...")
    from src.chunker import clean_text
    dirty = "Hello\x00World\x07  with   weird\x1f spaces.\n\n\n\nNew para."
    out = clean_text(dirty)
    if "\x00" in out or "\x07" in out or "\x1f" in out:
        print(f"  FAIL: control chars survived: {out!r}")
        return False
    if "  " in out:
        print(f"  FAIL: double spaces survived: {out!r}")
        return False
    if "\n\n\n" in out:
        print(f"  FAIL: triple newlines survived")
        return False
    print(f"  OK: clean output preserves content, drops noise")
    return True


def check_paragraph_split_returns_non_empty() -> bool:
    print("[2/6] split_paragraphs yields non-empty chunks above MIN_CHUNK...")
    from src.chunker import split_paragraphs, MIN_CHUNK_CHARS
    text = "First paragraph with enough content to count as a real chunk.\n\nSecond chunk that also has plenty of text inside it.\n\nshort."
    chunks = split_paragraphs(text)
    if not chunks:
        print("  FAIL: no chunks produced")
        return False
    for c in chunks:
        if len(c) < MIN_CHUNK_CHARS:
            print(f"  FAIL: chunk below MIN_CHUNK_CHARS ({MIN_CHUNK_CHARS}): {c!r}")
            return False
    print(f"  OK: produced {len(chunks)} chunks all >= {MIN_CHUNK_CHARS} chars")
    return True


def check_long_paragraph_splits_by_sentence() -> bool:
    print("[3/6] paragraphs over MAX_CHUNK_CHARS split on sentence boundaries...")
    from src.chunker import split_paragraphs, MAX_CHUNK_CHARS
    long_para = ". ".join(["This is sentence number {}".format(i) for i in range(100)]) + "."
    chunks = split_paragraphs(long_para)
    if len(chunks) < 2:
        print(f"  FAIL: long paragraph not split, got {len(chunks)} chunks")
        return False
    for c in chunks:
        if len(c) > MAX_CHUNK_CHARS + 50:  # small slop for tail sentence
            print(f"  FAIL: chunk exceeds MAX_CHUNK_CHARS ({MAX_CHUNK_CHARS}): {len(c)} chars")
            return False
    print(f"  OK: long paragraph split into {len(chunks)} chunks, all under {MAX_CHUNK_CHARS} chars")
    return True


def check_chunk_id_is_deterministic() -> bool:
    print("[4/6] chunk_id is deterministic for same (doc_id, index, text)...")
    from src.chunker import chunk_id
    a = chunk_id("doc1", 0, "Same text here.")
    b = chunk_id("doc1", 0, "Same text here.")
    c = chunk_id("doc1", 1, "Same text here.")  # different index
    d = chunk_id("doc2", 0, "Same text here.")  # different doc_id
    if a != b:
        print(f"  FAIL: same inputs gave different IDs: {a} vs {b}")
        return False
    if a == c or a == d:
        print(f"  FAIL: collision across docs/indices: a={a}, c={c}, d={d}")
        return False
    print(f"  OK: deterministic across re-runs, unique across (doc_id, index)")
    return True


def check_chunker_processes_all_silver_files() -> bool:
    print("[5/6] chunker writes gold JSON for every silver file...")
    result = subprocess.run(
        [sys.executable, "-m", "src.chunker"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"  FAIL: exit {result.returncode}\n  stderr: {result.stderr}")
        return False
    silver_count = len(list(SILVER_DIR.glob("*.json")))
    gold_count = len(list(GOLD_DIR.glob("*_chunks.json")))
    if gold_count != silver_count:
        print(f"  FAIL: expected {silver_count} gold files, got {gold_count}")
        return False
    print(f"  OK: {gold_count} gold chunk files written, one per silver file")
    return True


def check_gold_chunks_have_required_schema() -> bool:
    print("[6/6] every gold chunk has the required schema...")
    required = {"chunk_id", "doc_id", "file_name", "version", "chunk_index",
                "text", "char_count", "markers"}
    for gf in GOLD_DIR.glob("*_chunks.json"):
        chunks = json.loads(gf.read_text(encoding="utf-8"))
        if not chunks:
            print(f"  WARN: {gf.name} produced no chunks")
            continue
        for chunk in chunks:
            missing = required - set(chunk.keys())
            if missing:
                print(f"  FAIL: {gf.name} chunk missing fields: {missing}")
                return False
            if chunk["char_count"] != len(chunk["text"]):
                print(f"  FAIL: char_count mismatch in {gf.name}")
                return False
    print(f"  OK: every chunk has all 8 required fields with consistent counts")
    return True


def main():
    print("=" * 60)
    print("FossilRAG — PR 3 chunker validation")
    print("=" * 60)
    setup()
    checks = [
        check_clean_removes_control_chars,
        check_paragraph_split_returns_non_empty,
        check_long_paragraph_splits_by_sentence,
        check_chunk_id_is_deterministic,
        check_chunker_processes_all_silver_files,
        check_gold_chunks_have_required_schema,
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
