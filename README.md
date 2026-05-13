# FossilRAG

A serverless, self-healing document enrichment system for Dinosaur Whisperer.

FossilRAG ingests business documents (PPTX, PDF, text), processes them through a
serverless ETL (AWS Lambda + S3), extracts textual "DNA", chunks content into
semantic "fossil layers", generates embeddings, and exposes a FastAPI for search
and structured enrichment.

## Use Case: Automated Enrichment Pipeline

Ingests semi-structured business reports and incident logs. Extracts key markers
(dates, metrics, error codes) using regex + LLM. Enriches a structured database
with versioned fossil layers so downstream consumers (chatbots, dashboards, AI
agents) can query the latest state or any historical version.

## Mutations Implemented (5)

| Mutation | Purpose |
|---|---|
| Self-Healing Idempotency | DynamoDB manifest skips already-indexed chunks on re-runs |
| Auto-Scaling Lambda with DLQ | Reserved concurrency + dead-letter queue for burst traffic |
| Prompt Fossilization | Cache LLM prompt/response pairs for instant reuse |
| Time-Travel Query | Compare any two versions of a document, diff markers |
| Fine-Tuning Dataset Builder | Export gold chunks as JSONL instruction/response pairs |

## Architecture

```
S3 raw → Lambda extract → S3 silver → SQS → Lambda chunk+embed → S3 gold
                                                                       │
                                                          DynamoDB manifest
                                                                       │
                                                                       ▼
                                                          Lambda FastAPI (Mangum)
                                                                  │
                                                                  ▼
                                          /excavate · /mutate · /time-travel · /export/finetune
```

## Components

| Component | Description |
|---|---|
| 1. Document Ingestion | Lambda extracts text + markers from PDF/PPTX/TXT |
| 2. Cleaning & Chunking | Lambda cleans and splits text into semantic chunks |
| 3. Embedding & Indexing | sentence-transformers + FAISS, idempotent via DynamoDB |
| 4. Retrieval API | FastAPI on Lambda with Mangum, public Function URL |
| 5. Infrastructure as Code | CloudFormation, IAM, lifecycle policies, cost tags |
| 6. Containerization | Docker + docker-compose with LocalStack for offline testing |

## Repo structure

```
fossilrag/
├── README.md                       # this file
├── requirements.txt
├── .env.example
├── src/                            # local pipeline + FastAPI app
│   ├── extractor.py                # PR 2
│   ├── markers.py                  # PR 2
│   ├── chunker.py                  # PR 3
│   ├── embedder.py                 # PR 3
│   ├── manifest.py                 # PR 3 (Mutation 1)
│   ├── api/
│   │   ├── main.py                 # PR 4-7
│   │   └── mutate_handler.py       # PR 5
│   ├── prompt_cache.py             # PR 5 (Mutation 3)
│   ├── time_travel.py              # PR 6 (Mutation 4)
│   └── finetune_builder.py         # PR 7 (Mutation 5)
├── lambda/                         # PR 9 — production Lambda handlers
├── infra/                          # PR 9 — CloudFormation IaC
├── tests/
│   └── generate_samples.py         # sample business reports
└── Dockerfile, docker-compose.yml  # PR 8 — containerization
```

## Quick start (local)

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env, add GEMINI_API_KEY

python tests/generate_samples.py
python run_pipeline.py
uvicorn src.api.main:app --reload
```

Then visit `http://localhost:8000/docs`.

## Development plan (PRs)

This project is built across 9 PRs, each adding one component or mutation. See
the PR history on the `main` branch for the incremental development path.
