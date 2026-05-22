#!/bin/bash
# Creates LocalStack resources that mirror the production AWS setup.
# Runs automatically when LocalStack starts.

awslocal s3 mb s3://fossilrag-raw
awslocal s3 mb s3://fossilrag-silver
awslocal s3 mb s3://fossilrag-gold

awslocal dynamodb create-table \
  --table-name fossilrag-manifest \
  --attribute-definitions AttributeName=chunk_id,AttributeType=S \
  --key-schema AttributeName=chunk_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

awslocal dynamodb create-table \
  --table-name fossilrag-enrichment \
  --attribute-definitions AttributeName=doc_id,AttributeType=S AttributeName=version,AttributeType=N \
  --key-schema AttributeName=doc_id,KeyType=HASH AttributeName=version,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

awslocal sqs create-queue --queue-name fossilrag-chunk-dlq
awslocal sqs create-queue \
  --queue-name fossilrag-chunk-queue \
  --attributes '{"RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:eu-north-1:000000000000:fossilrag-chunk-dlq\",\"maxReceiveCount\":\"3\"}"}'

echo "LocalStack resources ready."
