"""
Validation for Mutation 3 — Prompt Fossilization.

5 checks covering local-backend storage, content-keyed lookup, cache
hit behavior, and the interface contract shared with the production
DynamoDB backend.

Run:
    python tests/test_prompt_cache.py
"""

import os
import shutil
import sys
from pathlib import Path

os.environ["MANIFEST_BACKEND"] = "local"

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "data" / "cache"
sys.path.insert(0, str(ROOT))


def reset_cache():
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)


def check_unseen_prompt_returns_none() -> bool:
    print("[1/5] get_cached returns None for a never-seen prompt...")
    reset_cache()
    from src.prompt_cache import get_cached
    result = get_cached("a totally fresh prompt that we have not cached")
    if result is not None:
        print(f"  FAIL: expected None, got {result!r}")
        return False
    print(f"  OK: unseen prompt returns None")
    return True


def check_save_then_get_roundtrip() -> bool:
    print("[2/5] save_to_cache followed by get_cached returns stored value...")
    reset_cache()
    from src.prompt_cache import get_cached, save_to_cache
    save_to_cache("prompt A", "response A")
    if get_cached("prompt A") != "response A":
        print(f"  FAIL: roundtrip mismatch")
        return False
    print(f"  OK: save -> get roundtrip works")
    return True


def check_different_prompts_are_isolated() -> bool:
    print("[3/5] different prompts cache to different keys...")
    reset_cache()
    from src.prompt_cache import get_cached, save_to_cache
    save_to_cache("prompt A", "response A")
    save_to_cache("prompt B", "response B")
    if get_cached("prompt A") != "response A":
        print(f"  FAIL: prompt A got wrong response")
        return False
    if get_cached("prompt B") != "response B":
        print(f"  FAIL: prompt B got wrong response")
        return False
    print(f"  OK: prompts are isolated by content hash")
    return True


def check_same_prompt_overwrites() -> bool:
    print("[4/5] saving same prompt twice updates the cached value...")
    reset_cache()
    from src.prompt_cache import get_cached, save_to_cache
    save_to_cache("prompt X", "old response")
    save_to_cache("prompt X", "new response")
    if get_cached("prompt X") != "new response":
        print(f"  FAIL: expected 'new response', got {get_cached('prompt X')!r}")
        return False
    print(f"  OK: re-save updates the cached value")
    return True


def check_cache_stats_count() -> bool:
    print("[5/5] cache_stats reports the right count for local backend...")
    reset_cache()
    from src.prompt_cache import save_to_cache, cache_stats
    save_to_cache("p1", "r1")
    save_to_cache("p2", "r2")
    save_to_cache("p3", "r3")
    stats = cache_stats()
    if stats.get("backend") != "local":
        print(f"  FAIL: stats backend is {stats.get('backend')}")
        return False
    if stats.get("cached_prompts") != 3:
        print(f"  FAIL: expected 3 cached prompts, got {stats.get('cached_prompts')}")
        return False
    print(f"  OK: stats reports backend={stats['backend']}, cached_prompts=3")
    return True


def main():
    print("=" * 60)
    print("FossilRAG - PR 4 prompt_cache (Mutation 3) validation")
    print("=" * 60)
    checks = [
        check_unseen_prompt_returns_none,
        check_save_then_get_roundtrip,
        check_different_prompts_are_isolated,
        check_same_prompt_overwrites,
        check_cache_stats_count,
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
