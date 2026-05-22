"""
Component 2 — Text Cleaning & Semantic Chunking.

Reads silver JSON files, cleans text, splits into semantic chunks
(by paragraph), assigns stable chunk_ids, writes to GOLD_DIR.

python -m src.chunker
"""

import hashlib
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SILVER_DIR = Path(os.environ.get("SILVER_DIR", "data/silver"))
GOLD_DIR = Path(os.environ.get("GOLD_DIR", "data/gold"))
GOLD_DIR.mkdir(parents=True, exist_ok=True)

MIN_CHUNK_CHARS = 50
MAX_CHUNK_CHARS = 1000


def clean_text(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; further split long paragraphs by sentence."""
    raw = re.split(r"\n\s*\n", text)
    chunks = []
    for para in raw:
        para = para.strip()
        if not para:
            continue
        if len(para) <= MAX_CHUNK_CHARS:
            if len(para) >= MIN_CHUNK_CHARS:
                chunks.append(para)
        else:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            current = ""
            for sent in sentences:
                if len(current) + len(sent) <= MAX_CHUNK_CHARS:
                    current = (current + " " + sent).strip()
                else:
                    if len(current) >= MIN_CHUNK_CHARS:
                        chunks.append(current)
                    current = sent
            if len(current) >= MIN_CHUNK_CHARS:
                chunks.append(current)
    return chunks


def chunk_id(doc_id: str, index: int, text: str) -> str:
    key = f"{doc_id}::{index}::{text[:64]}"
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def process_silver_file(silver_path: Path) -> list[dict]:
    record = json.loads(silver_path.read_text(encoding="utf-8"))
    cleaned = clean_text(record["text"])
    paragraphs = split_paragraphs(cleaned)

    chunks = []
    for i, para in enumerate(paragraphs):
        cid = chunk_id(record["doc_id"], i, para)
        chunks.append({
            "chunk_id": cid,
            "doc_id": record["doc_id"],
            "file_name": record["file_name"],
            "version": record["version"],
            "chunk_index": i,
            "text": para,
            "char_count": len(para),
            "markers": record.get("markers", {}),
        })

    out_path = GOLD_DIR / f"{record['doc_id']}_v{record['version']}_chunks.json"
    out_path.write_text(json.dumps(chunks, indent=2), encoding="utf-8")
    print(f"  {record['file_name']} v{record['version']} -> {len(chunks)} chunks -> {out_path.name}")
    return chunks


def run():
    silver_files = list(SILVER_DIR.glob("*.json"))
    if not silver_files:
        print(f"No silver files found in {SILVER_DIR}. Run src.extractor first.")
        return
    print(f"Chunking {len(silver_files)} silver file(s)...")
    total = 0
    for sf in silver_files:
        chunks = process_silver_file(sf)
        total += len(chunks)
    print(f"Chunking complete. {total} total chunks written to {GOLD_DIR}.")


if __name__ == "__main__":
    run()
