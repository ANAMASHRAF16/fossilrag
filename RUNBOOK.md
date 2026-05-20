# FossilRAG Runbook

Operational procedures for deploying, monitoring, and recovering the FossilRAG pipeline in AWS.

## Quick Reference

| Operation | Command / Path |
|---|---|
| Deploy infrastructure | `aws cloudformation deploy --template-file infra/cloudformation.yaml --stack-name fossilrag ...` |
| Local end-to-end test | `docker-compose up` |
| Tail extract Lambda logs | `aws logs tail /aws/lambda/fossilrag-extract --follow --region eu-north-1` |
| Drain the DLQ | `python infra/drain_dlq.py` (procedure documented below) |
| Force re-embed a document | Delete its rows from `fossilrag-manifest`, drop a new file in raw bucket |

## Deployment Procedure

### Prerequisites
- AWS CLI configured with `aws configure` (Access Key + Secret Key with admin or stack-deployment permissions)
- Docker Desktop running locally (for building the Lambda container image)
- ECR repository created (`aws ecr create-repository --repository-name fossilrag`)
- A Gemini API key in your secrets store or env var

### One-time setup

```bash
# 1. Build and push the Lambda Docker image
docker build -t fossilrag:latest .
docker tag fossilrag:latest <account>.dkr.ecr.eu-north-1.amazonaws.com/fossilrag:latest

aws ecr get-login-password --region eu-north-1 | \
  docker login --username AWS --password-stdin <account>.dkr.ecr.eu-north-1.amazonaws.com

docker push <account>.dkr.ecr.eu-north-1.amazonaws.com/fossilrag:latest

# 2. Deploy CloudFormation stack
aws cloudformation deploy \
  --template-file infra/cloudformation.yaml \
  --stack-name fossilrag \
  --capabilities CAPABILITY_NAMED_IAM \
  --region eu-north-1 \
  --parameter-overrides \
    AccountId=<your-account-id> \
    GeminiApiKey=<your-key> \
    EcrImageUri=<account>.dkr.ecr.eu-north-1.amazonaws.com/fossilrag:latest

# 3. Verify the API
API_URL=$(aws cloudformation describe-stacks --stack-name fossilrag --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
curl "${API_URL}health"
```

### Per-update deployment

```bash
# After code changes:
docker build -t fossilrag:latest .
docker tag fossilrag:latest <account>.dkr.ecr.eu-north-1.amazonaws.com/fossilrag:latest
docker push <account>.dkr.ecr.eu-north-1.amazonaws.com/fossilrag:latest

# Force Lambda to pull the new image
aws lambda update-function-code \
  --function-name fossilrag-api \
  --image-uri <account>.dkr.ecr.eu-north-1.amazonaws.com/fossilrag:latest \
  --region eu-north-1
```

## Monitoring

### CloudWatch alarms to set up (post-deploy)

| Alarm | Threshold | What it means |
|---|---|---|
| `fossilrag-chunk-dlq-not-empty` | `ApproximateNumberOfMessages > 0` for 5 min | A message has failed 3 times — needs human investigation |
| `fossilrag-extract-errors` | `Errors > 5` in 5 min on `fossilrag-extract` | Likely malformed file batch or IAM issue |
| `fossilrag-api-5xx` | `5XXError > 1%` over 5 min on the API Lambda | Gemini outage, FAISS load failure, or memory exhaustion |
| `fossilrag-api-cold-starts` | `Duration > 5s` at p99 | Lambda cold-start spike; consider provisioned concurrency |

### Useful log queries (CloudWatch Logs Insights)

```
# All Mutation 2 partial-batch failures across recent runs
fields @timestamp, @message
| filter @message like /batchItemFailures/
| sort @timestamp desc
| limit 50

# Documents that hit DLQ
fields @timestamp, @message
| filter @message like /FAILED/
| stats count() by bin(5m)

# Average extraction latency
fields @duration
| filter @type = "REPORT"
| stats avg(@duration), max(@duration), p99(@duration)
```

## Recovery Procedures

### Mutation 2 in action: a poison message lands in the DLQ

**Symptoms:** `fossilrag-chunk-dlq-not-empty` alarm fires. Some documents fail to embed.

**Investigation:**
1. Read the DLQ message body to find the offending S3 key:
   ```bash
   aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 10 \
     --region eu-north-1 --query 'Messages[*].Body'
   ```
2. Pull the silver JSON and find the failing chunk:
   ```bash
   aws s3 cp s3://fossilrag-silver-<account>/silver/<doc_id>_v1.json -
   ```
3. Check chunk-embed Lambda logs for the actual exception:
   ```bash
   aws logs filter-log-events --log-group-name /aws/lambda/fossilrag-chunk-embed \
     --filter-pattern <doc_id> --region eu-north-1
   ```

**Recovery:**
- If the failure is **transient** (rate limit, network blip): redrive the DLQ back to the main queue:
  ```bash
  aws sqs start-message-move-task \
    --source-arn <dlq-arn> \
    --destination-arn <main-queue-arn>
  ```
- If the failure is **systemic** (malformed silver JSON, code bug): fix the code, deploy via the "Per-update deployment" procedure above, then redrive.
- If the failure is **data-specific** (corrupted source document): delete the message from the DLQ; tell the user to re-upload a clean version.

### Force re-embedding of a single document

**When:** a document's chunks need to be regenerated (e.g., better extraction logic shipped, but DocumentX's manifest entries are stale).

```bash
DOC_ID=<doc-id>

# 1. Delete manifest entries for this doc
aws dynamodb scan \
  --table-name fossilrag-manifest \
  --filter-expression "doc_id = :did" \
  --expression-attribute-values "{\":did\":{\"S\":\"$DOC_ID\"}}" \
  --query "Items[*].chunk_id.S" --output text |
xargs -n1 -I{} aws dynamodb delete-item \
  --table-name fossilrag-manifest \
  --key "{\"chunk_id\":{\"S\":\"{}\"}}"

# 2. Re-upload the source file (any change to its name will trigger a new doc_id;
#    same name will reuse the same doc_id and re-embed the chunks because
#    the manifest is now empty)
aws s3 cp <local-file> s3://fossilrag-raw-<account>/
```

The pipeline will fire: extract → silver → SQS → chunk_embed (no skips since manifest empty) → gold + manifest repopulated.

### Restoring service when Gemini is down

The `/mutate` endpoint **already degrades gracefully** to structured fallback when Gemini fails (returns `mode: "structured_fallback"` instead of `mode: "gemini"`). No operator action needed for short outages.

For extended Gemini outages (>4 hours), consider:
1. Disabling the cache TTL temporarily so cached responses don't age out
2. Posting a status banner on the consuming frontend warning of reduced quality

## Cost Notes

### Steady-state monthly cost estimate (10K docs/month)

| Resource | Monthly cost |
|---|---|
| Lambda invocations | ~$12 |
| S3 storage (500 GB) | ~$11.50 |
| DynamoDB on-demand | ~$3 |
| SQS messages | <$1 |
| Gemini API (with Mutation 3 cache) | ~$8 |
| **Total** | **~$35/month** |

### Cost optimisations in place

1. **Mutation 1 (Self-Healing Idempotency)** — re-runs cost ~$0.05 instead of ~$50. 1000× saving on the second run onwards.
2. **Mutation 3 (Prompt Fossilization)** — cache hits cost ~$0 vs ~$0.0008 per Gemini call.
3. **Gold S3 lifecycle policy** — objects older than 90 days move to STANDARD_IA (40% cheaper storage).
4. **DynamoDB on-demand billing** — no idle costs, scales with actual usage.
5. **Reserved concurrency cap on chunk-embed** — prevents accidental cost spikes when uploading bulk.
6. **Cost tags** — every resource has `project=fossilrag` tag for cost-allocation reports.

### What would blow up cost

- Removing the manifest → 1000× more embedding API calls
- Removing the prompt cache → ~$50/month extra at modest LLM volume
- Setting `ReservedConcurrentExecutions: 1000` (no cap) → could exhaust DynamoDB throughput and inflate Lambda spend during a bulk upload

## Local Development

```bash
# 1. Boot local stack (LocalStack + 3 Lambdas + 1 FastAPI server)
docker-compose up

# 2. Drop a test file into the local raw bucket
aws --endpoint-url=http://localhost:4566 s3 cp \
  data/raw/q1_operations_report.txt \
  s3://fossilrag-raw/

# 3. Wait for the pipeline to flow through (~30s including embedding)
sleep 30

# 4. Query the API
curl "http://localhost:8000/health"
curl "http://localhost:8000/excavate?q=error+code&top_k=3"
curl -X POST "http://localhost:8000/mutate?query=summarise+all+incidents"
```

Same flow as production — just runs locally against LocalStack instead of real AWS.

## Disaster Recovery

| Failure mode | Recovery time | Procedure |
|---|---|---|
| API Lambda code corruption | ~5 min | Redeploy previous ECR image tag: `aws lambda update-function-code --image-uri <previous-tag>` |
| DynamoDB manifest data loss | ~hours | Restore from point-in-time backup (enable in CloudFormation if needed) |
| Whole stack accidentally deleted | ~30 min | Re-run the one-time deploy procedure; S3 data is retained via lifecycle policies if `DeletionPolicy: Retain` was set on buckets |
| FAISS index in S3 corrupted | ~30 min | Wipe `s3://fossilrag-gold-<account>/gold/`, clear manifest, re-trigger pipeline by re-copying files from raw to silver |

## On-call Contact

For production incidents, follow your team's normal on-call rotation. This runbook captures the FossilRAG-specific recovery paths; standard AWS troubleshooting (IAM, networking, billing) goes through your platform team.
