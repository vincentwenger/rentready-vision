"""Step 53: transaction permissions remain least privilege."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TABLE_ARN = (
    'arn:aws:dynamodb:${var.aws_region}:'
    '${data.aws_caller_identity.current.account_id}:'
    'table/${local.dynamodb_table_name}'
)


def terraform():
    return (
        ROOT / "infra/terraform/main.tf"
    ).read_text(encoding="utf-8")


def test_worker_transaction_permission_is_table_scoped():
    source = (
        ROOT / "infra/terraform/step53_transaction_iam.tf"
    ).read_text(encoding="utf-8")

    resource = source.split(
        'resource "aws_iam_role_policy" '
        '"worker_step53_inspection_transactions" {',
        1,
    )[1]

    assert 'name = "step53-inspection-transactions"' in resource
    assert "role = aws_iam_role.cool_worker.id" in resource
    assert '"dynamodb:TransactWriteItems"' in resource
    assert TABLE_ARN in resource
    assert '"dynamodb:*"' not in resource

    # Existing artifact and database permissions must not
    # change just to introduce Step 53 transactions.
    existing = terraform().split(
        'Sid    = "UpdateInspectionState"',
        1,
    )[1].split('      },', 1)[0]

    assert '"dynamodb:TransactWriteItems"' not in existing


def test_api_transaction_permission_is_table_scoped():
    import re

    source = (
        ROOT / "infra/terraform/step53_transaction_iam.tf"
    ).read_text(encoding="utf-8")

    assert (
        'resource "aws_iam_role_policy" '
        '"api_step53_inspection_transactions"'
    ) in source

    assert re.search(
        r"^\s*role\s*=\s*var\.api_runtime_role_name\s*$",
        source,
        re.MULTILINE,
    )

    assert '"dynamodb:TransactWriteItems"' in source
    assert TABLE_ARN in source
    assert '"dynamodb:*"' not in source

    # The old producer policy is not attached to the API role.
    # Do not rely on it for Step 53 permissions.
    producer = terraform().split(
        'resource "aws_iam_policy" "processing_producer" {',
        1,
    )[1].split(
        'resource "aws_iam_instance_profile"',
        1,
    )[0]

    assert "TransactInspectionJobs" not in producer


def test_api_policy_generator_stays_consistent():
    source = (
        ROOT / "scripts/build_step40_iam.py"
    ).read_text(encoding="utf-8")

    statement = next(
        line for line in source.splitlines()
        if 'statement("InspectionState"' in line
    )

    assert '"dynamodb:TransactWriteItems"' in statement
    assert "table_arn" in statement


def test_worker_lifecycle_role_not_expanded():
    source = (
        ROOT / "infra/terraform/worker_lifecycle.tf"
    ).read_text(encoding="utf-8")

    assert '"dynamodb:TransactWriteItems"' not in source
