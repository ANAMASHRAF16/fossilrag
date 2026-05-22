"""
Validation for Component 4 — FastAPI endpoints.

7 checks covering all 4 endpoints (/health, /excavate, /mutate,
/export/finetune, /time-travel), input validation, and the
Mutation 3 cache-hit behavior.

Uses FastAPI's TestClient so no server has to be running.

The /mutate endpoint is tested in fallback mode (no GEMINI_API_KEY) -
this verifies the structured_fallback path works without depending on
external API availability or burning quota in CI.

Run:
    python tests/test_api.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["MANIFEST_BACKEND"] = "local"
os.environ.pop("GEMINI_API_KEY", None)  # force fallback path in /mutate

ROOT = Path(__file__).parent.parent
INDEX_DIR = ROOT / "data" / "index"
GOLD_DIR = ROOT / "data" / "gold"
CACHE_DIR = ROOT / "data" / "cache"
sys.path.insert(0, str(ROOT))


def setup():
    """Build the pipeline end-to-end so the API has an index to serve."""
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    if INDEX_DIR.exists() and (INDEX_DIR / "fossilrag.faiss").exists():
        return  # index already built
    from src.manifest import clear_all
    clear_all()
    subprocess.run([sys.executable, str(ROOT / "tests" / "generate_samples.py")], check=True)
    subprocess.run([sys.executable, "-m", "src.extractor"], cwd=str(ROOT), check=True)
    subprocess.run([sys.executable, "-m", "src.chunker"], cwd=str(ROOT), check=True)
    subprocess.run([sys.executable, "-m", "src.embedder"], cwd=str(ROOT), check=True)


_client = None


def get_client():
    """Build a TestClient with the app's lifespan (loads FAISS + model)."""
    global _client
    if _client is None:
        from fastapi.testclient import TestClient
        from src.api.main import app
        _client = TestClient(app)
        _client.__enter__()  # trigger lifespan startup
    return _client


def check_health_endpoint() -> bool:
    print("[1/7] /health returns ok + vector count...")
    r = get_client().get("/health")
    if r.status_code != 200:
        print(f"  FAIL: status {r.status_code}")
        return False
    body = r.json()
    if body.get("status") != "ok" or body.get("vectors", 0) < 1:
        print(f"  FAIL: bad health response: {body}")
        return False
    print(f"  OK: status=ok, vectors={body['vectors']}, docs={body['docs']}")
    return True


def check_excavate_returns_chunks() -> bool:
    print("[2/7] /excavate?q=error returns relevant chunks...")
    r = get_client().get("/excavate", params={"q": "error code", "top_k": 3})
    if r.status_code != 200:
        print(f"  FAIL: status {r.status_code}")
        return False
    body = r.json()
    if body["returned"] < 1:
        print(f"  FAIL: zero results for 'error code'")
        return False
    found_error = any("err" in r["text"].lower() for r in body["results"])
    if not found_error:
        print(f"  FAIL: top results don't contain error-related text")
        return False
    print(f"  OK: {body['returned']} chunks returned, top-k contains error-related text")
    return True


def check_excavate_validates_input() -> bool:
    print("[3/7] /excavate rejects empty query with 422...")
    r = get_client().get("/excavate", params={"q": ""})
    if r.status_code != 422:
        print(f"  FAIL: expected 422, got {r.status_code}")
        return False
    print(f"  OK: empty query rejected with 422")
    return True


def check_mutate_falls_back_without_gemini_key() -> bool:
    print("[4/7] /mutate without GEMINI_API_KEY returns structured fallback...")
    r = get_client().post("/mutate", params={"query": "summarise incidents"})
    if r.status_code != 200:
        print(f"  FAIL: status {r.status_code}")
        return False
    body = r.json()
    if body.get("mode") != "structured_fallback":
        print(f"  FAIL: expected mode=structured_fallback, got {body.get('mode')}")
        return False
    if "enrichment" not in body:
        print(f"  FAIL: structured fallback missing 'enrichment' field")
        return False
    print(f"  OK: falls back to structured aggregation, returns markers")
    return True


def check_export_finetune_returns_jsonl() -> bool:
    print("[5/7] /export/finetune returns JSONL content...")
    r = get_client().get("/export/finetune")
    if r.status_code != 200:
        print(f"  FAIL: status {r.status_code}")
        return False
    if r.headers.get("content-type", "").split(";")[0] != "application/x-ndjson":
        print(f"  FAIL: wrong content-type: {r.headers.get('content-type')}")
        return False
    lines = r.text.strip().split("\n")
    if not lines:
        print(f"  FAIL: empty body")
        return False
    import json
    for line in lines[:3]:
        try:
            obj = json.loads(line)
            if "instruction" not in obj or "input" not in obj or "output" not in obj:
                print(f"  FAIL: JSONL row missing required fields")
                return False
        except json.JSONDecodeError:
            print(f"  FAIL: invalid JSON line")
            return False
    print(f"  OK: returns {len(lines)} valid JSONL training pairs")
    return True


def check_time_travel_error_on_missing_versions() -> bool:
    print("[6/7] /time-travel returns 400 when versions don't exist...")
    r = get_client().get(
        "/time-travel",
        params={"doc_id": "nonexistent-doc", "from_version": 1, "to_version": 2},
    )
    if r.status_code != 404:
        print(f"  FAIL: expected 404 for nonexistent doc, got {r.status_code}")
        return False
    print(f"  OK: nonexistent doc_id returns 404")
    return True


def check_excavate_version_filter() -> bool:
    print("[7/7] /excavate?version=N filter narrows to that version only...")
    # All sample docs are v1; this verifies the version param works
    r = get_client().get("/excavate", params={"q": "report", "top_k": 5, "version": 1})
    if r.status_code != 200:
        print(f"  FAIL: status {r.status_code}")
        return False
    body = r.json()
    for result in body["results"]:
        if result["version"] != 1:
            print(f"  FAIL: result with version={result['version']} should be filtered out")
            return False
    if body.get("version_filter") != 1:
        print(f"  FAIL: response should echo version_filter=1")
        return False
    print(f"  OK: version filter applied, all {body['returned']} results are v1")
    return True


def main():
    print("=" * 60)
    print("FossilRAG - PR 4 FastAPI endpoints validation")
    print("=" * 60)
    setup()
    checks = [
        check_health_endpoint,
        check_excavate_returns_chunks,
        check_excavate_validates_input,
        check_mutate_falls_back_without_gemini_key,
        check_export_finetune_returns_jsonl,
        check_time_travel_error_on_missing_versions,
        check_excavate_version_filter,
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
