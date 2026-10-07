# Step 49: disabled by default until the guarded worker has been deployed.
variable "worker_lifecycle_enabled" {
  type    = bool
  default = false
}

variable "worker_idle_shutdown_enabled" {
  type    = bool
  default = false
}

variable "worker_idle_timeout_seconds" {
  type    = number
  default = 600
  validation {
    condition     = var.worker_idle_timeout_seconds >= 600 && floor(var.worker_idle_timeout_seconds) == var.worker_idle_timeout_seconds
    error_message = "Use an integer idle timeout of at least 600 seconds."
  }
}

variable "api_runtime_role_name" {
  type    = string
  default = "rentready-vision-api-ec2"
}

variable "step49_api_artifact_s3_key" {
  description = "Exact checksum-pinned Step 49 API package key, prepared locally."
  type        = string
  default     = null
}

resource "aws_iam_role_policy" "api_step49_artifact" {
  count = var.worker_lifecycle_enabled && var.step49_api_artifact_s3_key != null ? 1 : 0
  name  = "step49-read-api-artifact"
  role  = var.api_runtime_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["s3:GetObject"], Resource = "arn:aws:s3:::${local.artifact_bucket_name}/${var.step49_api_artifact_s3_key}" }]
  })
}

locals {
  lifecycle_name = "${local.prefix}-worker-lifecycle"
  worker_arn     = "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.cool_worker.id}"
  state_arn      = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.dynamodb_table_name}"
}

data "archive_file" "worker_lifecycle" {
  count       = var.worker_lifecycle_enabled ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/worker-lifecycle.zip"
  source {
    filename = "worker_lifecycle.py"
    content  = file("${path.module}/../../app/worker_lifecycle.py")
  }
  source {
    filename = "worker_lifecycle_handler.py"
    content  = file("${path.module}/../lambda/worker_lifecycle_handler.py")
  }
}

resource "aws_cloudwatch_log_group" "worker_lifecycle" {
  count             = var.worker_lifecycle_enabled ? 1 : 0
  name              = "/aws/lambda/${local.lifecycle_name}"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_iam_role" "worker_lifecycle" {
  count = var.worker_lifecycle_enabled ? 1 : 0
  name  = local.lifecycle_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "worker_lifecycle" {
  count = var.worker_lifecycle_enabled ? 1 : 0
  name  = "step49-exact-worker-control"
  role  = aws_iam_role.worker_lifecycle[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ec2:StartInstances", "ec2:StopInstances"], Resource = local.worker_arn },
      { Effect = "Allow", Action = ["ec2:DescribeInstances"], Resource = "*" },
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Scan"], Resource = local.state_arn },
      { Effect = "Allow", Action = ["sqs:GetQueueAttributes"], Resource = aws_sqs_queue.processing.arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.worker_lifecycle[0].arn}:*" }
    ]
  })
}

resource "aws_lambda_function" "worker_lifecycle" {
  count                          = var.worker_lifecycle_enabled ? 1 : 0
  function_name                  = local.lifecycle_name
  role                           = aws_iam_role.worker_lifecycle[0].arn
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  handler                        = "worker_lifecycle_handler.handler"
  filename                       = data.archive_file.worker_lifecycle[0].output_path
  source_code_hash               = data.archive_file.worker_lifecycle[0].output_base64sha256
  timeout                        = 45
  memory_size                    = 128
  reserved_concurrent_executions = 1
  environment {
    variables = {
      DDB_TABLE                    = local.dynamodb_table_name
      COOL_WORKER_INSTANCE_ID       = aws_instance.cool_worker.id
      PROCESSING_QUEUE_URL          = aws_sqs_queue.processing.id
      WORKER_IDLE_TIMEOUT_SECONDS   = tostring(var.worker_idle_timeout_seconds)
      WORKER_IDLE_SHUTDOWN_ENABLED  = tostring(var.worker_idle_shutdown_enabled)
    }
  }
  depends_on = [aws_iam_role_policy.worker_lifecycle, aws_cloudwatch_log_group.worker_lifecycle]
  tags       = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "worker_lifecycle_errors" {
  count               = var.worker_lifecycle_enabled ? 1 : 0
  alarm_name          = "${local.lifecycle_name}-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.worker_lifecycle[0].function_name }
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_rule" "worker_lifecycle" {
  count               = var.worker_lifecycle_enabled ? 1 : 0
  name                = "${local.lifecycle_name}-reconcile"
  schedule_expression = "rate(1 minute)"
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_target" "worker_lifecycle" {
  count = var.worker_lifecycle_enabled ? 1 : 0
  rule  = aws_cloudwatch_event_rule.worker_lifecycle[0].name
  arn   = aws_lambda_function.worker_lifecycle[0].arn
  input = jsonencode({ action = "reconcile" })
}

resource "aws_lambda_permission" "worker_lifecycle_schedule" {
  count         = var.worker_lifecycle_enabled ? 1 : 0
  statement_id  = "Step49EventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.worker_lifecycle[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.worker_lifecycle[0].arn
}

resource "aws_iam_role_policy" "api_worker_wake" {
  count = var.worker_lifecycle_enabled ? 1 : 0
  name  = "step49-invoke-worker-lifecycle"
  role  = var.api_runtime_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.worker_lifecycle[0].arn }]
  })
}

output "worker_lifecycle_function_name" {
  value = var.worker_lifecycle_enabled ? aws_lambda_function.worker_lifecycle[0].function_name : null
}
