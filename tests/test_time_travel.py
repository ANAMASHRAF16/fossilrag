"""
Validation for Mutation 4 — Time-Travel Query.

5 checks covering version discovery, version listing, chunk
diffing, marker delta computation, and error handling.

Run:
    python tests/test_time_travel.py
"""

import json
import os
import shutil
import sys
from pathlib import Path

os.environ["MANIFEST_BACKEND"] = "local"

ROOT = Path(__file__).parent.parent
GOLD_DIR = ROOT / "data" / "gold"
sys.path.insert(0, str(ROOT))


def make_fake_doc(doc_id: str, version: int, chunks: list[dict]):
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLD_DIR / f"{doc_id}_v{version}_chunks.json"
    path.write_text(json.dumps(chunks, indent=2), encoding="utf-8")


def setup_two_versions():
    """Create v1 and v2 of a fake doc that share some chunks and differ on others."""
    if GOLD_DIR.exists():
        for f in GOLD_DIR.glob("test-doc_v*_chunks.json"):
            f.unlink()
    v1 = [
        {"chunk_id": "shared-1", "doc_id": "test-doc", "file_name": "t.txt",
         "version": 1, "chunk_index": 0, "text": "shared content",
         "markers": {"dates": ["Jan 1, 2026"], "metrics": [], "error_codes": []}},
        {"chunk_id": "shared-2", "doc_id": "test-doc", "file_name": "t.txt",
         "version": 1, "chunk_index": 1, "text": "also shared",
         "markers": {"dates": [], "metrics": ["100ms"], "error_codes": []}},
        {"chunk_id": "only-v1", "doc_id": "test-doc", "file_name": "t.txt",
         "version": 1, "chunk_index": 2, "text": "removed in v2",
         "markers": {"dates": [], "metrics": [], "error_codes": ["ERR-001"]}},
    ]
    v2 = [
        {"chunk_id": "shared-1", "doc_id": "test-doc", "file_name": "t.txt",
         "version": 2, "chunk_index": 0, "text": "shared content",
         "markers": {"dates": ["Jan 1, 2026"], "metrics": [], "error_codes": []}},
        {"chunk_id": "shared-2", "doc_id": "test-doc", "file_name": "t.txt",
         "version": 2, "chunk_index": 1, "text": "also shared",
         "markers": {"dates": [], "metrics": ["100ms"], "error_codes": []}},
        {"chunk_id": "only-v2", "doc_id": "test-doc", "file_name": "t.txt",
         "version": 2, "chunk_index": 2, "text": "added in v2",
         "markers": {"dates": ["Feb 15, 2026"], "metrics": ["500ms"], "error_codes": ["ERR-002"]}},
    ]
    make_fake_doc("test-doc", 1, v1)
    make_fake_doc("test-doc", 2, v2)


def cleanup():
    for f in GOLD_DIR.glob("test-doc_v*_chunks.json"):
        f.unlink()


def check_available_versions_finds_both() -> bool:
    print("[1/5] available_versions returns sorted list...")
    setup_two_versions()
    from src.time_travel import available_versions
    versions = available_versions("test-doc")
    if versions != [1, 2]:
        print(f"  FAIL: expected [1, 2], got {versions}")
        return False
    print(f"  OK: versions = {versions}")
    return True


def check_unknown_doc_returns_empty() -> bool:
    print("[2/5] unknown doc_id returns empty version list...")
    from src.time_travel import available_versions
    versions = available_versions("nonexistent-doc-id")
    if versions != []:
        print(f"  FAIL: expected [], got {versions}")
        return False
    print(f"  OK: unknown doc returns empty list")
    return True


def check_compare_detects_added_chunks() -> bool:
    print("[3/5] compare_versions correctly identifies added chunks...")
    from src.time_travel import compare_versions
    result = compare_versions("test-doc", 1, 2)
    if result["chunks"]["added"] != 1:
        print(f"  FAIL: expected added=1, got {result['chunks']['added']}")
        return False
    if result["chunks"]["removed"] != 1:
        print(f"  FAIL: expected removed=1, got {result['chunks']['removed']}")
        return False
    if result["chunks"]["unchanged"] != 2:
        print(f"  FAIL: expected unchanged=2, got {result['chunks']['unchanged']}")
        return False
    print(f"  OK: added=1, removed=1, unchanged=2 — diff correct")
    return True


def check_marker_changes_computed() -> bool:
    print("[4/5] compare_versions surfaces new dates/metrics/errors...")
    from src.time_travel import compare_versions
    result = compare_versions("test-doc", 1, 2)
    changes = result["marker_changes"]
    if "Feb 15, 2026" not in changes["new_dates"]:
        print(f"  FAIL: new date missing from new_dates: {changes['new_dates']}")
        return False
    if "500ms" not in changes["new_metrics"]:
        print(f"  FAIL: new metric missing: {changes['new_metrics']}")
        return False
    if "ERR-002" not in changes["new_error_codes"]:
        print(f"  FAIL: new error missing: {changes['new_error_codes']}")
        return False
    print(f"  OK: marker_changes lists all new dates, metrics, errors")
    cleanup()
    return True


def check_same_version_comparison_is_noop() -> bool:
    print("[5/5] comparing version to itself yields zero deltas...")
    setup_two_versions()
    from src.time_travel import compare_versions
    result = compare_versions("test-doc", 1, 1)
    if result["chunks"]["added"] != 0 or result["chunks"]["removed"] != 0:
        print(f"  FAIL: v1 vs v1 should be zero deltas, got {result['chunks']}")
        return False
    print(f"  OK: v1 vs v1 reports zero added, zero removed")
    cleanup()
    return True


def main():
    print("=" * 60)
    print("FossilRAG - PR 4 time_travel (Mutation 4) validation")
    print("=" * 60)
    checks = [
        check_available_versions_finds_both,
        check_unknown_doc_returns_empty,
        check_compare_detects_added_chunks,
        check_marker_changes_computed,
        check_same_version_comparison_is_noop,
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
