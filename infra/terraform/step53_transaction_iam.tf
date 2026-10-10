# Step 53: API inspection-job DynamoDB transactions.
# The API runtime role already exists outside this Terraform module.
# Grant only the missing action on the existing inspection table.

resource "aws_iam_role_policy" "api_step53_inspection_transactions" {
  name = "step53-inspection-transactions"
  role = var.api_runtime_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "TransactInspectionJobs"
        Effect   = "Allow"
        Action   = ["dynamodb:TransactWriteItems"]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.dynamodb_table_name}"
      }
    ]
  })
}

# Step 53: additional transaction permission for the COOL worker.
# Preserve the existing worker policy and deployment artifact access.

resource "aws_iam_role_policy" "worker_step53_inspection_transactions" {
  name = "step53-inspection-transactions"
  role = aws_iam_role.cool_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "TransactInspectionJobs"
        Effect   = "Allow"
        Action   = ["dynamodb:TransactWriteItems"]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.dynamodb_table_name}"
      }
    ]
  })
}
