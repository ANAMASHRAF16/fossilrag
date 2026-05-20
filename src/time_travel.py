"""
Mutation 4 — Time-Travel Query.

Every document version is stored separately (doc_id_v1.json, doc_id_v2.json).
This module lets callers query a specific version's chunks and compare
them to the latest, showing what markers/content changed.

Used by the /excavate endpoint's optional ?version= param.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GOLD_DIR = Path(os.environ.get("GOLD_DIR", "data/gold"))


def available_versions(doc_id: str) -> list[int]:
    """Return sorted list of version numbers available for a doc_id."""
    files = list(GOLD_DIR.glob(f"{doc_id}_v*_chunks.json"))
    versions = []
    for f in files:
        parts = f.stem.split("_v")
        if len(parts) >= 2:
            try:
                versions.append(int(parts[-1].replace("_chunks", "")))
            except ValueError:
                pass
    return sorted(versions)


def load_version_chunks(doc_id: str, version: int) -> list[dict]:
    path = GOLD_DIR / f"{doc_id}_v{version}_chunks.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def compare_versions(doc_id: str, v1: int, v2: int) -> dict:
    """
    Compare two versions of a document.
    Returns new chunks, removed chunks, and marker changes.
    """
    chunks_v1 = {c["chunk_id"]: c for c in load_version_chunks(doc_id, v1)}
    chunks_v2 = {c["chunk_id"]: c for c in load_version_chunks(doc_id, v2)}

    added = [c for cid, c in chunks_v2.items() if cid not in chunks_v1]
    removed = [c for cid, c in chunks_v1.items() if cid not in chunks_v2]
    unchanged = sum(1 for cid in chunks_v2 if cid in chunks_v1)

    def collect_markers(chunks):
        dates, metrics, errors = set(), set(), set()
        for c in chunks.values():
            m = c.get("markers", {})
            dates.update(m.get("dates", []))
            metrics.update(m.get("metrics", []))
            errors.update(m.get("error_codes", []))
        return {"dates": sorted(dates), "metrics": sorted(metrics), "error_codes": sorted(errors)}

    markers_v1 = collect_markers(chunks_v1)
    markers_v2 = collect_markers(chunks_v2)

    return {
        "doc_id": doc_id,
        "compared": {"from_version": v1, "to_version": v2},
        "chunks": {
            "added": len(added),
            "removed": len(removed),
            "unchanged": unchanged,
        },
        "new_chunks_preview": [c["text"][:120] + "..." for c in added[:3]],
        "removed_chunks_preview": [c["text"][:120] + "..." for c in removed[:3]],
        "marker_changes": {
            "new_dates": sorted(set(markers_v2["dates"]) - set(markers_v1["dates"])),
            "new_metrics": sorted(set(markers_v2["metrics"]) - set(markers_v1["metrics"])),
            "new_error_codes": sorted(set(markers_v2["error_codes"]) - set(markers_v1["error_codes"])),
        },
    }
