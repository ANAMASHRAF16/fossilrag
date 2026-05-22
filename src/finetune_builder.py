"""
Mutation 5 — Fine-Tuning Dataset Builder.

Exports gold chunks as JSONL in instruction/response format suitable
for fine-tuning an LLM. Each chunk becomes a training pair:
  instruction: "Summarise the following business report excerpt."
  input: <chunk text>
  output: <extracted markers as a structured summary>

Exposed via GET /export/finetune?doc_id=...
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.markers import extract_markers

load_dotenv()

GOLD_DIR = Path(os.environ.get("GOLD_DIR", "data/gold"))


INSTRUCTION = (
    "You are a document enrichment analyst. "
    "Extract and summarise key markers (dates, metrics, error codes) "
    "from the following business report excerpt."
)


def chunk_to_training_pair(chunk: dict) -> dict:
    markers = chunk.get("markers") or extract_markers(chunk["text"])
    parts = []
    if markers.get("dates"):
        parts.append("Dates: " + ", ".join(markers["dates"]))
    if markers.get("metrics"):
        parts.append("Metrics: " + ", ".join(markers["metrics"]))
    if markers.get("error_codes"):
        parts.append("Error codes: " + ", ".join(markers["error_codes"]))
    output = "; ".join(parts) if parts else "No structured markers identified."

    return {
        "instruction": INSTRUCTION,
        "input": chunk["text"],
        "output": output,
        "metadata": {
            "chunk_id": chunk["chunk_id"],
            "doc_id": chunk["doc_id"],
            "version": chunk["version"],
        },
    }


def build_dataset(doc_id: str | None = None) -> list[dict]:
    """Build training pairs from gold chunks. Filter by doc_id if given."""
    pattern = f"{doc_id}_v*_chunks.json" if doc_id else "*_chunks.json"
    files = list(GOLD_DIR.glob(pattern))

    pairs = []
    for f in files:
        chunks = json.loads(f.read_text(encoding="utf-8"))
        for chunk in chunks:
            if len(chunk["text"].strip()) < 50:
                continue
            pairs.append(chunk_to_training_pair(chunk))
    return pairs


def export_jsonl(doc_id: str | None = None) -> str:
    """Return JSONL string of all training pairs."""
    pairs = build_dataset(doc_id)
    return "\n".join(json.dumps(p) for p in pairs)
