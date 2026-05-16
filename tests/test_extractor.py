"""
Validation for Component 1 — Document Ingestion + Marker Extraction.

8 checks covering happy path, edge cases, and the contract between
the marker regex and the sample documents from PR 1.

Run:
    python tests/test_extractor.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW_DIR = ROOT / "data" / "raw"
SILVER_DIR = ROOT / "data" / "silver"

sys.path.insert(0, str(ROOT))


def setup():
    """Ensure samples exist; clean silver dir for a deterministic run."""
    if SILVER_DIR.exists():
        shutil.rmtree(SILVER_DIR)
    if not RAW_DIR.exists() or not any(RAW_DIR.glob("*.txt")):
        subprocess.run([sys.executable, str(ROOT / "tests" / "generate_samples.py")], check=True)


def check_markers_module_importable() -> bool:
    print("[1/8] markers module imports and exposes extract_markers...")
    try:
        from src.markers import extract_markers
        result = extract_markers("Test on March 15, 2026. Latency 250ms. ERROR-503.")
        assert set(result.keys()) == {"dates", "metrics", "error_codes"}, "missing keys"
        print(f"  OK: contract keys present {sorted(result.keys())}")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def check_marker_extraction_finds_all_families() -> bool:
    print("[2/8] markers extract all 3 families from seeded text...")
    from src.markers import extract_markers
    text = (
        "Quarterly report dated March 15, 2026. "
        "Peak latency 820ms, throughput 8500 req/s. "
        "ERROR-502 occurred at 14:32 UTC."
    )
    m = extract_markers(text)
    if not m["dates"] or not m["metrics"] or not m["error_codes"]:
        print(f"  FAIL: missing markers: {m}")
        return False
    print(f"  OK: dates={len(m['dates'])} metrics={len(m['metrics'])} errors={len(m['error_codes'])}")
    return True


def check_extractor_module_importable() -> bool:
    print("[3/8] extractor module imports and exposes process_file...")
    try:
        from src.extractor import process_file, doc_id, EXTRACTORS
        assert ".pdf" in EXTRACTORS and ".pptx" in EXTRACTORS and ".txt" in EXTRACTORS
        print(f"  OK: extractors registered for {sorted(EXTRACTORS.keys())}")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def check_doc_id_is_deterministic() -> bool:
    print("[4/8] doc_id is deterministic for same filename...")
    from src.extractor import doc_id
    a = doc_id(Path("report.pdf"))
    b = doc_id(Path("report.pdf"))
    c = doc_id(Path("different.pdf"))
    if a != b:
        print(f"  FAIL: same filename gave different IDs: {a} vs {b}")
        return False
    if a == c:
        print(f"  FAIL: different filenames gave same ID: {a}")
        return False
    print(f"  OK: report.pdf -> {a}, different.pdf -> {c}")
    return True


def check_extractor_runs_on_samples() -> bool:
    print("[5/8] extractor processes all sample files end-to-end...")
    result = subprocess.run(
        [sys.executable, "-m", "src.extractor"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"  FAIL: exit {result.returncode}\n  stderr: {result.stderr}")
        return False
    silver_files = list(SILVER_DIR.glob("*.json"))
    if len(silver_files) < 3:
        print(f"  FAIL: expected >=3 silver files, found {len(silver_files)}")
        return False
    print(f"  OK: {len(silver_files)} silver JSON files written")
    return True


def check_silver_json_has_required_fields() -> bool:
    print("[6/8] every silver JSON has the required schema...")
    required = {"doc_id", "file_name", "file_type", "version", "uploaded_at",
                "char_count", "markers", "text"}
    for sf in SILVER_DIR.glob("*.json"):
        rec = json.loads(sf.read_text(encoding="utf-8"))
        missing = required - set(rec.keys())
        if missing:
            print(f"  FAIL: {sf.name} missing fields: {missing}")
            return False
        if rec["char_count"] != len(rec["text"]):
            print(f"  FAIL: {sf.name} char_count {rec['char_count']} != len(text) {len(rec['text'])}")
            return False
    print(f"  OK: every silver JSON has all 8 required fields with consistent counts")
    return True


def check_unsupported_files_are_skipped() -> bool:
    print("[7/8] unsupported file types are skipped, not crashed on...")
    junk = RAW_DIR / "junk.xyz"
    junk.write_text("garbage", encoding="utf-8")
    try:
        from src.extractor import process_file
        result = process_file(junk)
        if result != {}:
            print(f"  FAIL: expected empty dict for unsupported type, got {result}")
            return False
        print(f"  OK: unsupported .xyz returns empty dict, no crash")
        return True
    finally:
        junk.unlink(missing_ok=True)


def check_empty_file_doesnt_crash() -> bool:
    print("[8/8] empty file is handled without crashing...")
    empty = RAW_DIR / "empty.txt"
    empty.write_text("", encoding="utf-8")
    try:
        from src.extractor import process_file
        rec = process_file(empty)
        if not rec or rec.get("char_count") != 0:
            print(f"  FAIL: empty file should yield record with char_count=0, got {rec.get('char_count')}")
            return False
        if rec["markers"] != {"dates": [], "metrics": [], "error_codes": []}:
            print(f"  FAIL: empty file should yield empty markers, got {rec['markers']}")
            return False
        print(f"  OK: empty file yields well-formed record with empty markers")
        return True
    finally:
        empty.unlink(missing_ok=True)
        for sf in SILVER_DIR.glob("*empty*.json"):
            sf.unlink()


def main():
    print("=" * 60)
    print("FossilRAG — PR 2 extractor + marker validation")
    print("=" * 60)
    setup()
    checks = [
        check_markers_module_importable,
        check_marker_extraction_finds_all_families,
        check_extractor_module_importable,
        check_doc_id_is_deterministic,
        check_extractor_runs_on_samples,
        check_silver_json_has_required_fields,
        check_unsupported_files_are_skipped,
        check_empty_file_doesnt_crash,
    ]
    results = [c() for c in checks]
    print("=" * 60)
    if all(results):
        print(f"PASS — {sum(results)}/{len(results)} checks succeeded")
        sys.exit(0)
    else:
        print(f"FAIL — {sum(results)}/{len(results)} checks succeeded")
        sys.exit(1)


if __name__ == "__main__":
    main()
