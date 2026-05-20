"""
Validation for Mutation 5 — Fine-Tuning Dataset Builder.

5 checks covering JSONL output format, per-doc filtering, marker
inclusion in the output field, short-chunk skipping, and the
training-pair contract that downstream fine-tuning consumers depend on.

Run:
    python tests/test_finetune_builder.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
GOLD_DIR = ROOT / "data" / "gold"
sys.path.insert(0, str(ROOT))


def setup():
    """Ensure gold chunks exist."""
    if not GOLD_DIR.exists() or not list(GOLD_DIR.glob("*_chunks.json")):
        subprocess.run([sys.executable, str(ROOT / "tests" / "generate_samples.py")], check=True)
        subprocess.run([sys.executable, "-m", "src.extractor"], cwd=str(ROOT), check=True)
        subprocess.run([sys.executable, "-m", "src.chunker"], cwd=str(ROOT), check=True)


def check_build_dataset_returns_pairs() -> bool:
    print("[1/5] build_dataset returns instruction/input/output triples...")
    from src.finetune_builder import build_dataset
    pairs = build_dataset()
    if not pairs:
        print(f"  FAIL: no pairs returned")
        return False
    required = {"instruction", "input", "output", "metadata"}
    for p in pairs:
        missing = required - set(p.keys())
        if missing:
            print(f"  FAIL: pair missing fields {missing}")
            return False
    print(f"  OK: {len(pairs)} pairs returned, all have 4 required fields")
    return True


def check_jsonl_export_is_valid_jsonl() -> bool:
    print("[2/5] export_jsonl produces valid JSONL (one JSON per line)...")
    from src.finetune_builder import export_jsonl
    output = export_jsonl()
    if not output:
        print(f"  FAIL: empty output")
        return False
    lines = output.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  FAIL: line {i} is not valid JSON: {e}")
            return False
    print(f"  OK: {len(lines)} valid JSONL lines")
    return True


def check_output_field_contains_markers() -> bool:
    print("[3/5] output field structures markers correctly...")
    from src.finetune_builder import build_dataset
    pairs = build_dataset()
    found_markers = False
    for p in pairs:
        out = p["output"]
        if "Dates:" in out or "Metrics:" in out or "Error codes:" in out:
            found_markers = True
            break
    if not found_markers:
        print(f"  FAIL: no pair has structured markers in output")
        return False
    print(f"  OK: at least one pair has structured markers in output field")
    return True


def check_per_doc_filtering() -> bool:
    print("[4/5] build_dataset with doc_id filters to that document only...")
    from src.finetune_builder import build_dataset
    all_pairs = build_dataset()
    if not all_pairs:
        print(f"  FAIL: no pairs in full dataset")
        return False
    target_doc = all_pairs[0]["metadata"]["doc_id"]
    filtered = build_dataset(doc_id=target_doc)
    if not filtered:
        print(f"  FAIL: filtered dataset is empty for {target_doc}")
        return False
    for p in filtered:
        if p["metadata"]["doc_id"] != target_doc:
            print(f"  FAIL: filtered set includes wrong doc {p['metadata']['doc_id']}")
            return False
    print(f"  OK: filtered to doc_id={target_doc}, {len(filtered)} pairs")
    return True


def check_short_chunks_excluded() -> bool:
    print("[5/5] chunks under 50 chars are excluded from the dataset...")
    # Create a fake short-chunk gold file
    fake = GOLD_DIR / "shorttest_v1_chunks.json"
    short_chunk = {
        "chunk_id": "short-001",
        "doc_id": "shorttest",
        "file_name": "short.txt",
        "version": 1,
        "chunk_index": 0,
        "text": "tiny",  # under 50 chars
        "markers": {"dates": [], "metrics": [], "error_codes": []},
    }
    fake.write_text(json.dumps([short_chunk]), encoding="utf-8")
    try:
        from src.finetune_builder import build_dataset
        pairs = build_dataset(doc_id="shorttest")
        if pairs:
            print(f"  FAIL: short chunk produced {len(pairs)} pairs, expected 0")
            return False
        print(f"  OK: chunks under 50 chars are filtered out")
        return True
    finally:
        fake.unlink()


def main():
    print("=" * 60)
    print("FossilRAG - PR 4 finetune_builder (Mutation 5) validation")
    print("=" * 60)
    setup()
    checks = [
        check_build_dataset_returns_pairs,
        check_jsonl_export_is_valid_jsonl,
        check_output_field_contains_markers,
        check_per_doc_filtering,
        check_short_chunks_excluded,
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
