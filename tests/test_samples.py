"""
Validation for the sample document generator.

Verifies that running generate_samples.py produces files containing the
markers the downstream pipeline will rely on. Without this validation,
PR 2's marker extractor would have nothing reliable to test against.

Run:
    python tests/test_samples.py
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW_DIR = ROOT / "data" / "raw"

EXPECTED_DOCS = {
    "q1_operations_report.txt",
    "q2_incident_log.txt",
    "system_architecture_notes.txt",
}

# Each doc must contain at least one of each marker family
REQUIRED_MARKERS = {
    "date": r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}"
            r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    "metric": r"\b\d+(?:\.\d+)?\s*(?:ms|s|sec|%|MB|GB|TB|KB|USD|\$|req/s|rpm)\b",
    "error_code": r"\b(?:ERR(?:OR)?[-_]?\d+|[45]\d{2}\s+(?:error|timeout))\b",
}


def run_generator() -> bool:
    """Invoke the generator as a subprocess; surface errors loudly."""
    print("[1/4] Running tests/generate_samples.py...")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "generate_samples.py")],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  FAIL: generator exited {result.returncode}")
        print(result.stderr)
        return False
    print(f"  OK: generator stdout = {result.stdout.strip().splitlines()[-1]}")
    return True


def assert_all_docs_present() -> bool:
    print("[2/4] Asserting all 3 sample documents exist...")
    actual = {f.name for f in RAW_DIR.glob("*.txt")}
    missing = EXPECTED_DOCS - actual
    if missing:
        print(f"  FAIL: missing {missing}")
        return False
    print(f"  OK: {sorted(actual)}")
    return True


def assert_each_doc_has_markers() -> bool:
    print("[3/4] Asserting every doc contains all 3 marker families...")
    all_ok = True
    for fname in EXPECTED_DOCS:
        path = RAW_DIR / fname
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        found = {}
        for marker_kind, pattern in REQUIRED_MARKERS.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            found[marker_kind] = len(matches)
        missing_kinds = [k for k, n in found.items() if n == 0]
        status = "OK " if not missing_kinds else "FAIL"
        print(f"  {status} {fname:40} dates={found['date']:2} metrics={found['metric']:2} errors={found['error_code']:2}")
        if missing_kinds:
            all_ok = False
    return all_ok


def assert_idempotent() -> bool:
    """Re-running the generator must not corrupt or duplicate output."""
    print("[4/4] Asserting re-run is idempotent (no duplicate files)...")
    count_before = len(list(RAW_DIR.glob("*.txt")))
    subprocess.run(
        [sys.executable, str(ROOT / "tests" / "generate_samples.py")],
        capture_output=True,
    )
    count_after = len(list(RAW_DIR.glob("*.txt")))
    if count_before != count_after:
        print(f"  FAIL: file count changed {count_before} -> {count_after}")
        return False
    print(f"  OK: file count stable at {count_after}")
    return True


def main():
    print("=" * 60)
    print("FossilRAG — PR 1 sample-data validation")
    print("=" * 60)

    checks = [run_generator, assert_all_docs_present, assert_each_doc_has_markers, assert_idempotent]
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
