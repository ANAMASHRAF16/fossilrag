"""
Generate sample business documents for testing the pipeline.
Creates TXT files (no extra dependencies) simulating real reports.
"""

import os
from pathlib import Path

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

DOCS = {
    "q1_operations_report.txt": """
Q1 2026 Operations Report — Dinosaur Whisperer Platform

Executive Summary
This report covers operational metrics for Q1 2026 (January 1 to March 31, 2026).
Overall system uptime was 99.2%, with 3 major incidents recorded.

Performance Metrics
Average API response time: 142ms
Peak load handled: 8500 req/s on March 15, 2026
Storage consumed: 2.4 TB across all fossil layers
Lambda cold start p99: 820ms
Document ingestion throughput: 1200 docs/hour

Incidents
ERROR-502 occurred on January 14, 2026 during the scheduled migration.
The root cause was a misconfigured IAM role causing 503 errors for 22 minutes.
ERROR-404 spike detected on February 28, 2026 — traced to an expired API key.
Resolution time: 8 minutes. Impact: 340 failed requests.

Infrastructure Costs
Total AWS spend: $1,240 USD for Q1
Lambda invocations: 4.2M at $0.000016 per request
S3 storage: 2.4 TB at $0.023/GB
DynamoDB reads: 12M at $0.25 per million

Recommendations
Increase reserved concurrency from 5 to 10 for the ingestion Lambda.
Migrate from gp2 to gp3 storage — saves 20% on storage costs.
Add a DLQ for the chunk-queue to capture failed embeddings.
Target: implement by April 15, 2026.
""",

    "q2_incident_log.txt": """
Q2 2026 Incident Log — Dinosaur Whisperer Platform

Period: April 1, 2026 to June 30, 2026

Incident 001 — April 3, 2026
Severity: High
Error: ERR-1024 database connection pool exhausted
Impact: 450 requests failed over 14 minutes
Metrics: connection wait time reached 5000ms, pool size was 10
Fix: increased DB_POOL_MAX_SIZE from 10 to 25. Resolved by 14:32 UTC.

Incident 002 — May 12, 2026
Severity: Medium
Error: 429 Too Many Requests from Gemini API
Impact: /mutate endpoint returned 500 errors for 6 minutes
Metrics: 1200 requests/minute exceeded Gemini free-tier limit of 60 RPM
Fix: added exponential backoff and switched to paid tier ($0.0001 per 1K tokens)
Resolved: May 12, 2026 at 09:47 UTC

Incident 003 — June 22, 2026
Severity: Low
Error: WARN-timeout on Lambda embedding function
Impact: 12 documents processed with 30s delay
Metrics: average embedding time 4200ms vs baseline 800ms
Root cause: sentence-transformers model loading on every cold start
Fix: load model outside handler, persist in Lambda execution context
Resolved: June 23, 2026

Performance Summary
Uptime: 99.7%
Total incidents: 3
MTTR (mean time to resolve): 9.3 minutes
Documents ingested: 18,400
Embeddings generated: 94,200
Average /excavate latency: 38ms
Average /mutate latency: 1240ms (1080ms of which is Gemini API call)
""",

    "system_architecture_notes.txt": """
FossilRAG System Architecture Notes
Last updated: March 10, 2026

Overview
FossilRAG is a serverless document enrichment platform built on AWS Lambda, S3, and DynamoDB.
Documents flow through three layers: raw (bronze), silver, and gold (medallion architecture).

Layer Definitions
Bronze/Raw Layer: S3 bucket fossilrag-raw. Stores uploaded files as-is.
Silver Layer: S3 bucket fossilrag-silver. Stores extracted text and metadata as JSON.
Gold Layer: S3 bucket fossilrag-gold. Stores cleaned chunks and FAISS embeddings.

Lambda Functions
extract-text: triggered by S3 ObjectCreated on fossilrag-raw. Timeout: 60s. Memory: 512 MB.
chunk-embed: triggered by SQS chunk-queue. BatchSize: 10. Reserved concurrency: 5.
fastapi-handler: Function URL. Timeout: 10s. Memory: 1024 MB.

SQS Configuration
chunk-queue: standard queue. MaxReceiveCount: 3. VisibilityTimeout: 120s.
chunk-queue-dlq: dead letter queue. Retention: 14 days.

DynamoDB Tables
fossilrag-manifest: pk=chunk_id. Tracks embedded chunks for idempotency.
fossilrag-enrichment: pk=doc_id, sk=version. Stores structured markers.

Cost Estimates (monthly at 10K docs/month)
Lambda: $2.40 (extract) + $8.60 (embed) + $1.20 (API) = $12.20
S3: 500 GB at $0.023/GB = $11.50
DynamoDB on-demand: ~$3.00
Total estimate: $26.70 per month

Error Handling
All Lambda functions implement exponential backoff on transient AWS errors.
DLQ captures documents that fail after 3 attempts.
ERROR-5xx responses from Gemini trigger fallback to structured marker extraction.
"""
}

for name, content in DOCS.items():
    path = RAW_DIR / name
    path.write_text(content.strip(), encoding="utf-8")
    print(f"Created: {path}")

print(f"\nSample documents written to {RAW_DIR}")
print("Now run the pipeline:")
print("  python -m src.extractor")
print("  python -m src.chunker")
print("  python -m src.embedder")
print("  uvicorn src.api.main:app --reload")
