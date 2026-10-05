"""Generate separate exact-resource API and setup policies; do not attach them."""
import argparse
import json
import re
from pathlib import Path


def statement(sid, actions, resources, condition=None):
    result = {"Sid": sid, "Effect": "Allow", "Action": actions, "Resource": resources}
    if condition:
        result["Condition"] = condition
    return result


def build_policies(*, account, region, bucket, table, queue, models=(), secret_arn=None,
                   parameter_name=None, kms_key_arn=None):
    if not re.fullmatch(r"\d{12}", account):
        raise ValueError("Account must be an exact 12-digit AWS account ID")
    for value in (region, bucket, table, queue):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError("Use exact AWS resource names without wildcards")
    if secret_arn and parameter_name:
        raise ValueError("Choose one secret source")
    for arn in (*models, *([secret_arn] if secret_arn else []), *([kms_key_arn] if kms_key_arn else [])):
        if not arn.startswith("arn:aws:") or "*" in arn or "REPLACE" in arn:
            raise ValueError("Use exact ARNs without placeholders or wildcards")
    if parameter_name and not re.fullmatch(r"/[A-Za-z0-9_./-]+", parameter_name):
        raise ValueError("Use an exact absolute Parameter Store name")
    bucket_arn = f"arn:aws:s3:::{bucket}"
    table_arn = f"arn:aws:dynamodb:{region}:{account}:table/{table}"
    api = [
        statement("InspectionObjects", ["s3:GetObject", "s3:PutObject", "s3:GetObjectTagging", "s3:PutObjectTagging",
                  "s3:GetObjectVersionTagging", "s3:PutObjectVersionTagging"],
                  [bucket_arn + "/inspections/*", bucket_arn + "/rentready/inspections/*"]),
        statement("InspectionState", ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"], table_arn),
        statement("EnqueueJobs", ["sqs:SendMessage"], f"arn:aws:sqs:{region}:{account}:{queue}"),
    ]
    # Some demo issue-detection routes invoke Bedrock in the API. Explicitly
    # pass the approved inference-profile and destination foundation-model ARNs.
    if models:
        api.append(statement("ApprovedModels", ["bedrock:InvokeModel"], list(models)))
    if secret_arn:
        api.append(statement("ReadOperatorSecret", ["secretsmanager:GetSecretValue"], secret_arn))
    if parameter_name:
        api.append(statement("ReadOperatorParameter", ["ssm:GetParameter"],
                             f"arn:aws:ssm:{region}:{account}:parameter{parameter_name}"))
    if kms_key_arn:
        if not (secret_arn or parameter_name):
            raise ValueError("KMS permission requires a secret source")
        service = "secretsmanager" if secret_arn else "ssm"
        api.append(statement("DecryptOperatorSecret", ["kms:Decrypt"], kms_key_arn,
                             {"StringEquals": {"kms:ViaService": f"{service}.{region}.amazonaws.com"}}))
    setup = [
        statement("ProvisionTable", ["dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:TagResource"], table_arn),
        statement("ConfigureMediaBucket", ["s3:CreateBucket", "s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketVersions",
                  "s3:GetBucketPolicy", "s3:PutBucketPolicy", "s3:GetBucketPolicyStatus", "s3:PutBucketOwnershipControls",
                  "s3:GetBucketOwnershipControls", "s3:GetBucketPublicAccessBlock", "s3:PutBucketPublicAccessBlock",
                  "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration", "s3:PutBucketCORS", "s3:GetBucketCORS",
                  "s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration"], bucket_arn),
    ]
    return {"api-runtime": {"Version": "2012-10-17", "Statement": api},
            "setup-only": {"Version": "2012-10-17", "Statement": setup}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("account", "region", "bucket", "table", "queue"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--model-arn", action="append", default=[])
    parser.add_argument("--secret-arn")
    parser.add_argument("--parameter-name")
    parser.add_argument("--kms-key-arn")
    parser.add_argument("--output-dir", type=Path, default=Path("local-artifacts/step40-iam"))
    args = parser.parse_args()
    policies = build_policies(account=args.account, region=args.region, bucket=args.bucket,
                             table=args.table, queue=args.queue, models=args.model_arn,
                             secret_arn=args.secret_arn, parameter_name=args.parameter_name, kms_key_arn=args.kms_key_arn)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, policy in policies.items():
        path = args.output_dir / (name + ".json")
        path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
