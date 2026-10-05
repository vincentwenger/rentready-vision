"""Brief, controlled worker IAM/SSM check; stop the worker afterward if idle.

Requires --start-and-stop and an initially stopped worker with an empty queue.
No job is enqueued and no video is processed by this script.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from datetime import datetime, timezone

WORKER = "i-0ecc68f9db17b668d"
QUEUE = "https://sqs.us-west-2.amazonaws.com/081087819788/rentready-vision-processing"
COUNTS = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible", "ApproximateNumberOfMessagesDelayed"]
ROOT = Path(__file__).resolve().parents[1]

REMOTE = r'''
import json, os, pwd, subprocess, sys, platform
from pathlib import Path
from dotenv import dotenv_values
from botocore.exceptions import ClientError

values = dotenv_values("/etc/environment")
names = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
if any(values.get(k) or os.environ.get(k) for k in names):
    raise RuntimeError("Unexpected static AWS credentials configured.")
os.environ.update({k: v for k, v in values.items() if v is not None})
user = pwd.getpwnam("ubuntu")
os.environ["HOME"] = user.pw_dir
# Python is launched as ubuntu by runuser. Changing uid inside an already
# running Python process can make /proc/self/auxv unreadable and break OpenCV's
# ARM CPU feature detection. Keep the real CPU baseline checks enabled.
with open("/proc/self/auxv", "rb") as auxv:
    cpu_information_readable = bool(auxv.read(16))
os.chdir("/opt/rentready-vision/current")
sys.path.insert(0, "/opt/rentready-vision/current")
from app.aws import session
import cv2

identity = session.client("sts").get_caller_identity()["Arn"]
checks = {
    "runs_as_unprivileged_worker_user": os.getuid() == user.pw_uid and os.getuid() != 0,
    "arm_cpu_information_readable": cpu_information_readable,
    "credentials_come_from_instance_role": session.get_credentials().method == "iam-role",
    "expected_worker_instance_role": identity == "arn:aws:sts::081087819788:assumed-role/rentready-vision-dev-cool-worker/i-0ecc68f9db17b668d",
    "official_cool_opencv_path": str(Path(cv2.__file__).resolve()).startswith("/opt/cool/"),
    "graviton_architecture": platform.machine() == "aarch64",
    "worker_service_active": subprocess.run(["systemctl", "is-active", "--quiet", "rentready-cool-worker.service"]).returncode == 0,
}
session.client("dynamodb").get_item(
    TableName="rentready-vision-dev",
    Key={"PK": {"S": "INSPECTION#step40-security-probe"}, "SK": {"S": "METADATA"}}
)
checks["inspection_state_read_allowed"] = True
head = session.client("s3").head_object(
    Bucket="rentready-vision-dev-081087819788",
    Key="rentready/inspections/7e8998a9-836f-490f-89f1-1431da8993a4/original/walkthrough.mp4"
)
checks["encrypted_inspection_object_read_allowed"] = head.get("ServerSideEncryption") == "AES256"
session.client("sqs").get_queue_attributes(QueueUrl="https://sqs.us-west-2.amazonaws.com/081087819788/rentready-vision-processing", AttributeNames=["QueueArn"])
checks["processing_queue_attributes_allowed"] = True

def denied(operation):
    try:
        operation()
        return False
    except ClientError as error:
        return error.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException")

checks["operator_token_read_denied"] = denied(lambda: session.client("ssm").get_parameter(Name="/rentready/api-token", WithDecryption=True))
checks["bucket_policy_read_denied"] = denied(lambda: session.client("s3").get_bucket_policy(Bucket="rentready-vision-dev-081087819788"))
checks["unassigned_dlq_access_denied"] = denied(lambda: session.client("sqs").get_queue_attributes(QueueUrl="https://sqs.us-west-2.amazonaws.com/081087819788/rentready-vision-processing-dlq", AttributeNames=["QueueArn"]))
print(json.dumps({"runtime_identity": identity, "opencv_version": cv2.__version__, "opencv_path": cv2.__file__, "checks": checks, "passed": all(checks.values())}))
'''


def state(ec2):
    return ec2.describe_instances(InstanceIds=[WORKER])["Reservations"][0]["Instances"][0]["State"]["Name"]


def queue_counts(sqs):
    attributes = sqs.get_queue_attributes(QueueUrl=QUEUE, AttributeNames=COUNTS)["Attributes"]
    return {key: int(attributes[key]) for key in COUNTS}


def wait_until(predicate, seconds, description):
    deadline = time.monotonic() + seconds
    next_notice = 0
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= next_notice:
            print(description, flush=True)
            next_notice = time.monotonic() + 20
        time.sleep(3)
    raise TimeoutError(description)


def run(session, output):
    from botocore.config import Config
    config = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
    ec2, sqs, ssm = (session.client(service, config=config) for service in ("ec2", "sqs", "ssm"))
    result = {"scope": "Live COOL worker SSM and runtime IAM check with controlled stop", "instance_id": WORKER,
              "started_at": datetime.now(timezone.utc).isoformat(), "checks": {}, "errors": [], "worker_start_requested": False}
    # Validate before entering the mutation/cleanup block. Never stop an instance
    # that was already running when this script was invoked.
    if state(ec2) != "stopped":
        raise RuntimeError("Worker must initially be stopped; no changes made.")
    before = queue_counts(sqs)
    if any(before.values()):
        raise RuntimeError("Processing queue must be empty; no changes made.")
    result["queue_before"] = before
    try:
        result["worker_start_requested"] = True
        print("Starting the stopped worker for the security check.", flush=True)
        ec2.start_instances(InstanceIds=[WORKER])
        wait_until(lambda: state(ec2) == "running", 180, "Waiting for worker startup...")

        def online():
            records = ssm.describe_instance_information(Filters=[{"Key": "InstanceIds", "Values": [WORKER]}])["InstanceInformationList"]
            return next((item for item in records if item["PingStatus"] == "Online"), None)

        info = wait_until(online, 240, "Waiting for the worker SSM Agent...")
        result["agent_version"] = info["AgentVersion"]
        result["checks"]["ssm_online_with_narrow_policy"] = True
        command = "runuser -u ubuntu -- env PYTHONPATH=/opt/cool/python_3.12/site-packages LD_LIBRARY_PATH=/opt/cool/cpp_sdk/lib /opt/cool/venvs/python_3.12/bin/python -B - <<'PY'\n" + REMOTE + "\nPY"
        command_id = ssm.send_command(InstanceIds=[WORKER], DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command], "executionTimeout": ["90"]}, TimeoutSeconds=60,
            Comment="Step40 read-only worker runtime IAM verification")["Command"]["CommandId"]
        result["command_id"] = command_id

        def finished():
            try:
                invocation = ssm.get_command_invocation(CommandId=command_id, InstanceId=WORKER)
            except ssm.exceptions.InvocationDoesNotExist:
                return None
            return invocation if invocation["Status"] not in ("Pending", "InProgress", "Delayed") else None

        invocation = wait_until(finished, 120, "Waiting for the read-only worker probe...")
        result["command_status"] = invocation["Status"]
        result["stderr_present"] = bool(invocation["StandardErrorContent"])
        result["checks"]["ssm_run_command_succeeds"] = invocation["Status"] == "Success"
        if invocation["Status"] == "Success":
            result["verification"] = json.loads(invocation["StandardOutputContent"])
            result["checks"]["runtime_checks_pass"] = result["verification"]["passed"]
        else:
            result["errors"].append("remote_probe_failed")
    except Exception as error:
        # Exception strings and command output are intentionally not serialized:
        # failed SDK calls must not accidentally expose credentials or secrets.
        result["errors"].append(type(error).__name__)
    finally:
        try:
            after = queue_counts(sqs)
            result["queue_after"] = after
            if any(after.values()):
                result["checks"]["worker_returned_to_stopped"] = False
                result["errors"].append("queue_activity_detected_worker_left_running_to_preserve_jobs")
            else:
                current = state(ec2)
                if current in ("running", "pending"):
                    print("Queue is idle; stopping the worker.", flush=True)
                    ec2.stop_instances(InstanceIds=[WORKER])
                wait_until(lambda: state(ec2) == "stopped", 180, "Waiting for the worker to stop...")
                result["checks"]["worker_returned_to_stopped"] = True
        except Exception as error:
            result["errors"].append("cleanup_" + type(error).__name__)
            result["checks"]["worker_returned_to_stopped"] = False
        result["passed"] = bool(result["checks"]) and all(result["checks"].values()) and not result["errors"]
        result["verified_at"] = datetime.now(timezone.utc).isoformat()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-and-stop", action="store_true", required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/step40/worker_runtime_security_verification.json")
    args = parser.parse_args()
    import boto3
    result = run(boto3.Session(profile_name=args.profile, region_name="us-west-2"), args.output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
