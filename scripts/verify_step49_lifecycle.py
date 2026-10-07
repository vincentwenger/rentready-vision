"""Read-only Step 49 infrastructure checks; never claims an end-to-end pass."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import boto3
from app.worker_lifecycle import WorkerLifecycle


def verify(session, *, instance_id, function_name, table_name, queue_url):
    checks = {}
    ec2 = session.client("ec2")
    instance = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
    checks["instance_restartable"] = instance["State"]["Name"] in {"running", "pending", "stopping", "stopped"}
    function = session.client("lambda").get_function_configuration(FunctionName=function_name)
    env = function.get("Environment", {}).get("Variables", {})
    checks["function_ready"] = function.get("State") == "Active" and function.get("LastUpdateStatus") == "Successful"
    checks["exact_instance"] = env.get("COOL_WORKER_INSTANCE_ID") == instance_id
    checks["exact_table"] = env.get("DDB_TABLE") == table_name
    checks["exact_queue"] = env.get("PROCESSING_QUEUE_URL") == queue_url
    checks["ten_minute_idle_timeout"] = env.get("WORKER_IDLE_TIMEOUT_SECONDS") == "600"
    checks["shutdown_enabled"] = env.get("WORKER_IDLE_SHUTDOWN_ENABLED") == "true"
    concurrency = session.client("lambda").get_function_concurrency(FunctionName=function_name)
    checks["serialized_controller"] = concurrency.get("ReservedConcurrentExecutions") == 1
    events = session.client("events")
    rule_name = function_name + "-reconcile"
    rule = events.describe_rule(Name=rule_name)
    checks["minute_schedule"] = rule.get("State") == "ENABLED" and rule.get("ScheduleExpression") == "rate(1 minute)"
    targets = events.list_targets_by_rule(Rule=rule_name)["Targets"]
    checks["scheduled_target"] = any(t["Arn"] == function["FunctionArn"] for t in targets)
    state = WorkerLifecycle(session.resource("dynamodb").Table(table_name), instance_id).read()
    checks["guarded_worker_seen"] = state.get("guard_version") == "step49/1.0"
    return {"step": 49, "infrastructure_passed": all(checks.values()), "checks": checks,
        "instance_state": instance["State"]["Name"], "worker_phase": state.get("phase"),
        "end_to_end_status": "PENDING_OPERATOR_UPLOAD_AND_IDLE_SHUTDOWN_TEST"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--profile")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--table", default="rentready-vision-dev")
    parser.add_argument("--queue-url", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/step49/live_infrastructure.json")
    args = parser.parse_args()
    result = verify(boto3.Session(profile_name=args.profile, region_name=args.region),
        instance_id=args.instance_id, function_name=args.function_name, table_name=args.table, queue_url=args.queue_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["infrastructure_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
