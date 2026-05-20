"""
Validation for Mutation 1 — Self-Healing Idempotency (manifest module).

5 checks covering local-backend storage, read-after-write, content-hash
detection, and the safety properties the production DynamoDB backend
will share.

Run:
    python tests/test_manifest.py

Note: this test only exercises the LOCAL backend (no AWS credentials
needed). The DynamoDB backend shares the same interface; PR 5 wires
it into Lambda and an integration test runs against a real table there.
"""

import os
import sys
from pathlib import Path

os.environ["MANIFEST_BACKEND"] = "local"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def reset_manifest():
    from src.manifest import clear_all
    clear_all()


def check_unprocessed_chunk_reports_false() -> bool:
    print("[1/5] is_processed returns False for a chunk we have never seen...")
    from src.manifest import is_processed, content_hash
    reset_manifest()
    result = is_processed("never-seen-chunk-id", content_hash("anything"))
    if result is not False:
        print(f"  FAIL: expected False, got {result}")
        return False
    print(f"  OK: unknown chunk reports False as expected")
    return True


def check_mark_then_check_roundtrip() -> bool:
    print("[2/5] mark_processed followed by is_processed returns True...")
    from src.manifest import is_processed, mark_processed, content_hash
    reset_manifest()
    h = content_hash("Some chunk text")
    mark_processed("chunk-001", "doc-001", h, version=1)
    if not is_processed("chunk-001", h):
        print(f"  FAIL: marked chunk reports unprocessed")
        return False
    print(f"  OK: mark -> check roundtrip works")
    return True


def check_content_hash_change_invalidates_cache() -> bool:
    print("[3/5] same chunk_id with different content hash = NOT processed...")
    from src.manifest import is_processed, mark_processed, content_hash
    reset_manifest()
    original_hash = content_hash("Original text")
    edited_hash = content_hash("Edited text")
    mark_processed("chunk-001", "doc-001", original_hash, version=1)
    if is_processed("chunk-001", edited_hash):
        print(f"  FAIL: edited chunk reported as already processed")
        return False
    if not is_processed("chunk-001", original_hash):
        print(f"  FAIL: original hash should still match")
        return False
    print(f"  OK: content hash change correctly invalidates the manifest entry")
    return True


def check_re_marking_is_idempotent() -> bool:
    print("[4/5] marking the same chunk twice does not corrupt state...")
    from src.manifest import is_processed, mark_processed, content_hash
    reset_manifest()
    h = content_hash("text")
    mark_processed("chunk-001", "doc-001", h, version=1)
    mark_processed("chunk-001", "doc-001", h, version=1)  # second time
    if not is_processed("chunk-001", h):
        print(f"  FAIL: state corrupted after duplicate mark")
        return False
    print(f"  OK: re-marking is idempotent (no-op semantically)")
    return True


def check_clear_all_wipes_state() -> bool:
    print("[5/5] clear_all() resets the manifest cleanly...")
    from src.manifest import is_processed, mark_processed, clear_all, content_hash
    h = content_hash("text")
    mark_processed("chunk-001", "doc-001", h, version=1)
    clear_all()
    if is_processed("chunk-001", h):
        print(f"  FAIL: clear_all did not wipe the manifest")
        return False
    print(f"  OK: clear_all() wipes state as expected")
    return True


def main():
    print("=" * 60)
    print("FossilRAG - PR 3 manifest (Mutation 1) validation")
    print("=" * 60)
    checks = [
        check_unprocessed_chunk_reports_false,
        check_mark_then_check_roundtrip,
        check_content_hash_change_invalidates_cache,
        check_re_marking_is_idempotent,
        check_clear_all_wipes_state,
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
