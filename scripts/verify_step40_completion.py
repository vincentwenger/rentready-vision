"""Check retained Step 40 evidence offline; this does not perform a fresh AWS audit."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "081087819788"
BUCKET = "rentready-vision-dev-" + ACCOUNT
API_ROLE = "arn:aws:iam::" + ACCOUNT + ":role/rentready-vision-api-ec2"
WORKER_ROLE = "arn:aws:iam::" + ACCOUNT + ":role/rentready-vision-dev-cool-worker"
PACKAGE_SHA = "854503187bd9d5ac6be9c3d43772b52722bb9342b7631b0187dc61c8b921e734"


def verify(root=ROOT):
    folder = root / "evaluation/step40"
    checks, hashes, errors = {}, {}, []

    def load(name):
        raw = (folder / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    def check(name, operation):
        try:
            checks[name] = bool(operation())
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            checks[name] = False
        if not checks[name]:
            errors.append(name)

    def passed(name, count=None):
        data = load(name)
        values = data.get("checks", {})
        return (data.get("passed") is True and not data.get("errors")
                and (count is None or len(values) == count)
                and all(value is True for value in values.values()))

    check("repository_security_pass", lambda: passed("repository_security_verification.json", 7))
    check("repository_tests_pass", lambda: passed("test_summary.json") and load("test_summary.json")["failures"] == 0)
    check("live_aws_https_and_object_pass", lambda: passed("final_live_security_verification.json", 13))
    check("hosted_upload_security_pass", lambda: passed("hosted_upload_security_verification.json", 15))
    check("api_role_configuration_and_simulation_pass", lambda: passed("ec2_api_role_policy_verification.json", 20)
          and load("ec2_api_role_policy_verification.json")["role_arn"] == API_ROLE)
    check("worker_management_policy_replacement_pass", lambda: passed("worker_management_policy_verification.json", 3))
    check("worker_role_simulation_pass", lambda: passed("worker_iam_policy_verification.json", 27)
          and load("worker_iam_policy_verification.json")["role_arn"] == WORKER_ROLE)

    def runtime(name, count, identity):
        data = load(name)
        proof = data["verification"]
        return (data["passed"] is True and data["command_status"] == "Success"
                and proof["passed"] is True and proof["runtime_identity"] == identity
                and len(proof["checks"]) == count and all(v is True for v in proof["checks"].values()))

    prefix = "arn:aws:sts::" + ACCOUNT + ":assumed-role/"
    check("actual_api_role_permissions_pass", lambda: runtime("ec2_api_runtime_verification.json", 8,
          prefix + "rentready-vision-api-ec2/i-0b86234abb75509b7"))
    check("actual_worker_role_permissions_pass", lambda: runtime("worker_runtime_security_verification.json", 13,
          prefix + "rentready-vision-dev-cool-worker/i-0ecc68f9db17b668d"))
    check("worker_returned_to_stopped", lambda: load("worker_runtime_security_verification.json")["checks"]["worker_returned_to_stopped"] is True)

    def https():
        data = load("public_https_auth_verification.json")
        return data["passed"] is True and set(data["domains"]) == {"rentreadyvision.com", "www.rentreadyvision.com"} and all(
            d["passed"] is True and not d["errors"] and len(d["checks"]) == 12
            and all(v is True for v in d["checks"].values()) for d in data["domains"].values())
    check("both_public_https_hostnames_pass", https)

    def cors():
        data = load("hosted_cors_verification.json")
        return data["passed"] is True and set(data["checks"]) == {
            "https://rentreadyvision.com", "https://www.rentreadyvision.com", "unapproved_origin"
        } and sum(len(v) for v in data["checks"].values()) == 22 and all(
            v is True for group in data["checks"].values() for v in group.values())
    check("approved_origins_and_unapproved_origin_pass", cors)

    def ec2():
        data = load("ec2_security_review_input.json")["servers"]
        def rules(values, ports):
            return len(values) == len(ports) and {r.get("FromPort") for r in values} == ports and all(
                r["IpProtocol"] == "tcp" and r["FromPort"] == r["ToPort"]
                and [p["CidrIp"] for p in r["IpRanges"]] == ["0.0.0.0/0"]
                and not r["Ipv6Ranges"] and not r["UserIdGroupPairs"] and not r["PrefixListIds"] for r in values)
        for label, inbound in (("api", {80, 443}), ("cool_worker", set())):
            machine = data[label]
            if machine["metadata_options"]["HttpTokens"] != "required" or machine["metadata_options"]["HttpPutResponseHopLimit"] != 1:
                return False
            if not machine["volumes"] or not all(v["encrypted"] is True for v in machine["volumes"]):
                return False
            if len(machine["security_groups"]) != 1:
                return False
            group = machine["security_groups"][0]
            if not rules(group["inbound"], inbound) or not rules(group["outbound"], {443}):
                return False
        return True
    check("ec2_disks_imdsv2_and_firewalls_pass", ec2)

    def resources():
        data = load("resource_policy_review_input.json")
        if data["table_resource_policy"] is not None or not data["bucket_policy"]["Statement"]:
            return False
        if not all(s["Effect"] == "Deny" for s in data["bucket_policy"]["Statement"]):
            return False
        for name in ("rentready-vision-processing", "rentready-vision-processing-dlq"):
            statements = data["queue_policies"][name]["Policy"]["Statement"]
            if len(statements) != 1:
                return False
            statement = statements[0]
            if (statement["Effect"] != "Allow" or statement["Principal"] != {"AWS": "arn:aws:iam::" + ACCOUNT + ":root"}
                or statement["Resource"] != "arn:aws:sqs:us-west-2:" + ACCOUNT + ":" + name or statement["Action"] != "SQS:*"):
                return False
        return data["queue_policies"]["rentready-vision-processing-dlq"]["RedriveAllowPolicy"] == {
            "redrivePermission": "byQueue", "sourceQueueArns": ["arn:aws:sqs:us-west-2:" + ACCOUNT + ":rentready-vision-processing"]}
    check("resource_policies_have_no_extra_principal_grants", resources)
    check("managed_operator_token_metadata_pass", lambda: load("resource_policy_review_input.json")["operator_token_metadata"] == {
          "Name": "/rentready/api-token", "Type": "SecureString", "Tier": "Standard", "KeyId": "alias/aws/ssm"})

    def package():
        data = load("api-package.json")
        return (data["sha256"] == PACKAGE_SHA and data["bucket"] == BUCKET
                and data["source_secret_scan_passed"] is True and len(data["files"]) == 38
                and all(hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() == f["sha256"] for f in data["files"]))
    check("repository_runtime_files_match_deployed_package", package)
    return {"step": 40, "mode": "retained_evidence_review", "scope": "Step 40 single-operator deployed security controls; no fresh AWS audit or new inference benchmark",
            "passed": not errors, "security_complete": not errors, "checks": checks, "errors": errors,
            "evidence_sha256": hashes, "git_publication": "not_checked_by_this_verifier",
            "reviewed_at": datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = verify(args.root)
    path = args.root / "evaluation/step40/completion_verification.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
