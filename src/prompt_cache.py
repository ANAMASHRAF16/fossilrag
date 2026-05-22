"""
Mutation 3 — Prompt Fossilization.

Caches successful LLM prompt+response pairs keyed by SHA-256 of the prompt.
On cache hit, returns the stored response instantly (0ms LLM latency).

Two backends:
  local    — JSON file in CACHE_DIR (Phase 1)
  dynamodb — DynamoDB table (Phase 2)
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND = os.environ.get("MANIFEST_BACKEND", "local")
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "data/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "prompt_fossils.json"
TABLE_NAME = os.environ.get("MANIFEST_TABLE", "fossilrag-manifest")
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")


def _prompt_key(prompt: str) -> str:
    return "prompt::" + hashlib.sha256(prompt.encode()).hexdigest()


def _load_local() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_local(cache: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_cached(prompt: str) -> str | None:
    key = _prompt_key(prompt)
    if BACKEND == "local":
        return _load_local().get(key, {}).get("response")
    else:
        import boto3
        table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)
        resp = table.get_item(Key={"chunk_id": key})
        item = resp.get("Item")
        return item.get("response") if item else None


def save_to_cache(prompt: str, response: str):
    key = _prompt_key(prompt)
    entry = {
        "response": response,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "prompt_preview": prompt[:100],
    }
    if BACKEND == "local":
        cache = _load_local()
        cache[key] = entry
        _save_local(cache)
    else:
        import boto3
        table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)
        table.put_item(Item={"chunk_id": key, **entry})


def cache_stats() -> dict:
    if BACKEND == "local":
        cache = _load_local()
        prompt_keys = [k for k in cache if k.startswith("prompt::")]
        return {"cached_prompts": len(prompt_keys), "backend": "local"}
    return {"backend": "dynamodb"}
