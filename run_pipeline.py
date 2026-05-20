"""
Run the full local pipeline in one shot.

Usage:
    python run_pipeline.py          # process docs in data/raw/
    python run_pipeline.py --fresh  # clear index + manifest first
"""

import sys


def main():
    fresh = "--fresh" in sys.argv

    if fresh:
        print("=== Clearing existing index and manifest ===")
        from src.manifest import clear_all
        clear_all()
        import shutil
        from pathlib import Path
        for d in ["data/silver", "data/gold", "data/index"]:
            p = Path(d)
            if p.exists():
                shutil.rmtree(p)
                p.mkdir(parents=True)
        print("Cleared.\n")

    print("=== Step 1: Extract text from documents ===")
    from src.extractor import run as extract
    extract()

    print("\n=== Step 2: Clean and chunk text ===")
    from src.chunker import run as chunk
    chunk()

    print("\n=== Step 3: Generate embeddings (idempotent) ===")
    from src.embedder import run as embed
    embed()

    print("\n=== Pipeline complete. Start the API with: ===")
    print("  uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    main()
