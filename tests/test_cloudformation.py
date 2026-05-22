"""
Validation for Component 5 (IaC) and Mutation 2 (Auto-Scaling Lambda with DLQ).

These checks validate the CloudFormation template structurally — they
verify that the production-mandatory properties are present without
actually deploying anything (which would cost real AWS resources and
require credentials).

Mutation 2 specifically requires:
  - SQS queue with a DLQ via RedrivePolicy
  - maxReceiveCount = 3 on the redrive policy
  - Lambda EventSourceMapping with BatchSize and ReportBatchItemFailures
  - ReservedConcurrentExecutions on the embed Lambda

Cost-optimisation requires:
  - Lifecycle policy on the gold S3 bucket
  - Project tags on every resource

Run:
    python tests/test_cloudformation.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CF_PATH = ROOT / "infra" / "cloudformation.yaml"


def load_template() -> dict:
    """Parse the CloudFormation YAML using a CFN-aware loader.

    CFN uses YAML tags like !GetAtt that PyYAML's safe_load chokes on.
    We register them as no-op constructors that just return the tag value.
    """
    import yaml

    class CFLoader(yaml.SafeLoader):
        pass

    def _generic(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return f"!{tag_suffix} {node.value}"
        if isinstance(node, yaml.SequenceNode):
            return {f"Fn::{tag_suffix}": loader.construct_sequence(node)}
        if isinstance(node, yaml.MappingNode):
            return {f"Fn::{tag_suffix}": loader.construct_mapping(node)}
        return None

    CFLoader.add_multi_constructor("!", _generic)
    with open(CF_PATH, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=CFLoader)


def get_resource(template: dict, logical_id: str) -> dict | None:
    return template.get("Resources", {}).get(logical_id)


def check_template_loads() -> bool:
    print("[1/8] cloudformation.yaml is syntactically valid YAML...")
    try:
        tpl = load_template()
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return False
    if not tpl.get("Resources"):
        print("  FAIL: template has no Resources section")
        return False
    print(f"  OK: {len(tpl['Resources'])} resources defined")
    return True


def check_three_s3_buckets() -> bool:
    print("[2/8] template defines raw/silver/gold S3 buckets...")
    tpl = load_template()
    for logical in ["RawBucket", "SilverBucket", "GoldBucket"]:
        r = get_resource(tpl, logical)
        if r is None or r["Type"] != "AWS::S3::Bucket":
            print(f"  FAIL: missing or wrong type for {logical}")
            return False
    print("  OK: RawBucket + SilverBucket + GoldBucket present")
    return True


def check_two_dynamodb_tables() -> bool:
    print("[3/8] template defines manifest + enrichment DynamoDB tables...")
    tpl = load_template()
    for logical in ["ManifestTable", "EnrichmentTable"]:
        r = get_resource(tpl, logical)
        if r is None or r["Type"] != "AWS::DynamoDB::Table":
            print(f"  FAIL: missing or wrong type for {logical}")
            return False
        if r["Properties"].get("BillingMode") != "PAY_PER_REQUEST":
            print(f"  FAIL: {logical} should use PAY_PER_REQUEST (on-demand) billing")
            return False
    print("  OK: both tables present with on-demand billing")
    return True


def check_mutation_2_dlq_wired() -> bool:
    print("[4/8] Mutation 2: ChunkQueue has RedrivePolicy with maxReceiveCount=3...")
    tpl = load_template()
    dlq = get_resource(tpl, "ChunkDLQ")
    if dlq is None or dlq["Type"] != "AWS::SQS::Queue":
        print("  FAIL: ChunkDLQ resource missing")
        return False
    queue = get_resource(tpl, "ChunkQueue")
    if queue is None:
        print("  FAIL: ChunkQueue resource missing")
        return False
    redrive = queue["Properties"].get("RedrivePolicy")
    if not redrive:
        print("  FAIL: ChunkQueue has no RedrivePolicy")
        return False
    if str(redrive.get("maxReceiveCount")) != "3":
        print(f"  FAIL: expected maxReceiveCount=3, got {redrive.get('maxReceiveCount')}")
        return False
    print("  OK: DLQ wired with maxReceiveCount=3")
    return True


def check_mutation_2_reserved_concurrency() -> bool:
    print("[5/8] Mutation 2: ChunkEmbedFunction has ReservedConcurrentExecutions...")
    tpl = load_template()
    fn = get_resource(tpl, "ChunkEmbedFunction")
    if fn is None:
        print("  FAIL: ChunkEmbedFunction missing")
        return False
    reserved = fn["Properties"].get("ReservedConcurrentExecutions")
    if reserved is None:
        print("  FAIL: no ReservedConcurrentExecutions set on chunk-embed Lambda")
        return False
    if not (1 <= int(reserved) <= 100):
        print(f"  FAIL: ReservedConcurrentExecutions={reserved} outside sensible range")
        return False
    print(f"  OK: ReservedConcurrentExecutions={reserved}")
    return True


def check_mutation_2_partial_batch_response() -> bool:
    print("[6/8] Mutation 2: EventSourceMapping uses ReportBatchItemFailures...")
    tpl = load_template()
    mapping = get_resource(tpl, "SQSTrigger")
    if mapping is None:
        print("  FAIL: SQSTrigger EventSourceMapping missing")
        return False
    response_types = mapping["Properties"].get("FunctionResponseTypes", [])
    if "ReportBatchItemFailures" not in response_types:
        print(f"  FAIL: ReportBatchItemFailures not in {response_types}")
        return False
    batch_size = mapping["Properties"].get("BatchSize")
    if batch_size is None or int(batch_size) < 1:
        print(f"  FAIL: BatchSize must be set and >= 1, got {batch_size}")
        return False
    print(f"  OK: ReportBatchItemFailures enabled, BatchSize={batch_size}")
    return True


def check_cost_optimisation_lifecycle() -> bool:
    print("[7/8] Cost optimisation: gold bucket has lifecycle policy...")
    tpl = load_template()
    gold = get_resource(tpl, "GoldBucket")
    if gold is None:
        print("  FAIL: GoldBucket missing")
        return False
    lifecycle = gold["Properties"].get("LifecycleConfiguration")
    if not lifecycle:
        print("  FAIL: no LifecycleConfiguration on gold bucket")
        return False
    rules = lifecycle.get("Rules", [])
    if not rules:
        print("  FAIL: lifecycle has no rules")
        return False
    print(f"  OK: gold bucket has {len(rules)} lifecycle rule(s)")
    return True


def check_cost_tags_on_resources() -> bool:
    print("[8/8] Cost optimisation: project tag on every taggable resource...")
    tpl = load_template()
    taggable_types = {"AWS::S3::Bucket", "AWS::DynamoDB::Table", "AWS::SQS::Queue",
                      "AWS::Lambda::Function"}
    untagged = []
    for logical, resource in tpl["Resources"].items():
        if resource["Type"] not in taggable_types:
            continue
        tags = resource["Properties"].get("Tags", [])
        if not any(t.get("Key") == "project" and t.get("Value") == "fossilrag" for t in tags):
            untagged.append(logical)
    if untagged:
        print(f"  FAIL: missing 'project=fossilrag' tag on: {untagged}")
        return False
    print("  OK: every taggable resource has project=fossilrag")
    return True


def main():
    print("=" * 60)
    print("FossilRAG - PR 5 CloudFormation + Mutation 2 validation")
    print("=" * 60)
    checks = [
        check_template_loads,
        check_three_s3_buckets,
        check_two_dynamodb_tables,
        check_mutation_2_dlq_wired,
        check_mutation_2_reserved_concurrency,
        check_mutation_2_partial_batch_response,
        check_cost_optimisation_lifecycle,
        check_cost_tags_on_resources,
    ]
    results = [c() for c in checks]
    print("=" * 60)
    if all(results):
        print(f"PASS - {sum(results)}/{len(results)} checks succeeded")
        sys.exit(0)
    print(f"FAIL - {sum(results)}/{len(results)} checks succeeded")
    sys.exit(1)


if __name__ == "__main__":
    main()
