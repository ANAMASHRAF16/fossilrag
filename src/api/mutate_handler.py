"""
/mutate endpoint handler.

Flow:
  1. Excavate top-k chunks for the query
  2. Build prompt from chunks + markers
  3. Check Prompt Fossil cache (Mutation 3) — return instantly on hit
  4. Call Gemini (gemini-1.5-flash)
  5. On Gemini failure, fall back to structured marker aggregation
  6. Store successful response in cache
"""

import os

import numpy as np
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite"


def build_prompt(query: str, chunks: list[dict]) -> str:
    context = "\n\n---\n\n".join(
        f"[{c['file_name']} v{c['version']} chunk {c['chunk_index']}]\n{c['text']}"
        for c in chunks
    )
    return (
        f"You are a document enrichment analyst for a fossil discovery system.\n"
        f"A user queried: \"{query}\"\n\n"
        f"Here are the most relevant document excerpts:\n\n{context}\n\n"
        f"Provide a structured enrichment summary including:\n"
        f"1. Key dates and timelines mentioned\n"
        f"2. Metrics and performance numbers\n"
        f"3. Error codes or issues identified\n"
        f"4. A 2-3 sentence executive summary\n"
        f"Be concise and factual. Only reference information present in the excerpts."
    )


def structured_fallback(query: str, chunks: list[dict]) -> dict:
    """Rule-based aggregation when Gemini is unavailable."""
    all_dates, all_metrics, all_errors = set(), set(), set()
    for c in chunks:
        m = c.get("markers", {})
        all_dates.update(m.get("dates", []))
        all_metrics.update(m.get("metrics", []))
        all_errors.update(m.get("error_codes", []))
    return {
        "mode": "structured_fallback",
        "query": query,
        "sources": [{"file": c["file_name"], "version": c["version"]} for c in chunks],
        "enrichment": {
            "dates": sorted(all_dates),
            "metrics": sorted(all_metrics),
            "error_codes": sorted(all_errors),
        },
    }


async def generate_mutation(app, query: str, top_k: int) -> dict:
    from src.prompt_cache import get_cached, save_to_cache

    # Step 1: excavate top-k chunks
    vec = app.state.model.encode([query], normalize_embeddings=True).astype(np.float32)
    distances, indices = app.state.index.search(vec, min(top_k, app.state.index.ntotal))
    chunks = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx >= 0:
            chunks.append(app.state.metadata[idx])

    if not chunks:
        return {"error": "No relevant chunks found for query."}

    # Step 2: build prompt
    prompt = build_prompt(query, chunks)

    # Step 3: Prompt Fossil cache hit? (Mutation 3)
    cached = get_cached(prompt)
    if cached:
        return {
            "query": query,
            "mode": "cache_hit",
            "gemini_response": cached,
            "sources": [{"file": c["file_name"], "version": c["version"]} for c in chunks],
        }

    # Step 4: Call Gemini
    if not GEMINI_API_KEY:
        return {**structured_fallback(query, chunks), "note": "GEMINI_API_KEY not set"}

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text

        # Step 5: Cache the successful response (Mutation 3)
        save_to_cache(prompt, text)

        return {
            "query": query,
            "mode": "gemini",
            "gemini_response": text,
            "sources": [{"file": c["file_name"], "version": c["version"]} for c in chunks],
        }
    except Exception as e:
        # Step 6: Fallback on Gemini error
        fallback = structured_fallback(query, chunks)
        fallback["gemini_error"] = str(e)
        return fallback
