provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  prefix              = "${var.project_name}-${var.environment}"
  s3_bucket_name      = var.s3_bucket_name
  dynamodb_table_name = var.dynamodb_table_name
  queue_name          = "${var.project_name}-processing"
  dlq_name            = "${var.project_name}-processing-dlq"
  common_tags = {
    Project     = "RentReady Vision"
    Environment = var.environment
    Runtime     = "OpenCV COOL ${var.cool_version}"
  }
}

resource "aws_s3_bucket" "media" {
  count  = var.manage_data_resources ? 1 : 0
  bucket = local.s3_bucket_name
  tags   = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "media" {
  count                   = var.manage_data_resources ? 1 : 0
  bucket                  = aws_s3_bucket.media[0].id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  count  = var.manage_data_resources ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "media" {
  count  = var.manage_data_resources ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  cors_rule {
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_origins = var.frontend_origins
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  count  = var.manage_data_resources ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  rule {
    id     = "expire-prototype-video"
    status = "Enabled"
    filter {
      prefix = "inspections/"
    }
    expiration {
      days = 30
    }
  }
}

resource "aws_dynamodb_table" "app" {
  count        = var.manage_data_resources ? 1 : 0
  name         = local.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"
  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled = true
  }
  tags = local.common_tags
}

resource "aws_sqs_queue" "processing_dlq" {
  name                      = local.dlq_name
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.common_tags
}

resource "aws_sqs_queue" "processing" {
  name                       = local.queue_name
  visibility_timeout_seconds = var.queue_visibility_timeout_seconds
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = var.queue_max_receive_count
  })
  tags = local.common_tags
}

resource "aws_sqs_queue_redrive_allow_policy" "processing_dlq" {
  queue_url = aws_sqs_queue.processing_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.processing.arn]
  })
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/rentready-vision/cool-worker"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${local.prefix}-processing-dlq-not-empty"
  alarm_description   = "RentReady processing jobs have reached the dead-letter queue."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = aws_sqs_queue.processing_dlq.name
  }
  tags = local.common_tags
}

resource "aws_iam_role" "cool_worker" {
  name = "${local.prefix}-cool-worker"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.cool_worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "cool_worker" {
  name = "rentready-worker-least-privilege"
  role = aws_iam_role.cool_worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid    = "ReadWriteRentReadyObjects"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "arn:aws:s3:::${local.s3_bucket_name}/inspections/*",
          "arn:aws:s3:::${local.s3_bucket_name}/runtime-evidence/*"
        ]
      },
      {
        Sid    = "UpdateInspectionState"
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem"
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.dynamodb_table_name}"
      },
      {
        Sid    = "ConsumeProcessingQueue"
        Effect = "Allow"
        Action = [
          "sqs:ChangeMessageVisibility",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ReceiveMessage"
        ]
        Resource = aws_sqs_queue.processing.arn
      },
      {
        Sid    = "WriteWorkerLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.worker.arn}:*"
      },
      {
        Sid      = "PublishProcessingMetrics"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "RentReadyVision/Processing"
          }
        }
      }
      ], length(var.bedrock_model_arns) == 0 ? [] : [
      {
        Sid    = "InvokeApprovedBedrockModels"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = var.bedrock_model_arns
      }
    ])
  })
}

resource "aws_iam_policy" "processing_producer" {
  name        = "${local.prefix}-processing-producer"
  description = "Attach to the RentReady API role so it can enqueue COOL processing jobs."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "EnqueueCoolProcessingJobs"
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = aws_sqs_queue.processing.arn
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_instance_profile" "cool_worker" {
  name = "${local.prefix}-cool-worker"
  role = aws_iam_role.cool_worker.name
}

resource "aws_security_group" "cool_worker" {
  name_prefix = "${local.prefix}-cool-worker-"
  description = "No inbound access; HTTPS egress for SSM and AWS APIs"
  vpc_id      = var.vpc_id

  egress {
    description = "HTTPS to SSM, S3, SQS, DynamoDB, CloudWatch, Bedrock, and package sources"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.prefix}-cool-worker" })
}

resource "aws_instance" "cool_worker" {
  ami                         = var.cool_ami_id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  associate_public_ip_address = var.associate_public_ip_address
  iam_instance_profile        = aws_iam_instance_profile.cool_worker.name
  vpc_security_group_ids      = [aws_security_group.cool_worker.id]
  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    environment     = var.environment
    aws_region      = var.aws_region
    s3_bucket       = local.s3_bucket_name
    ddb_table       = local.dynamodb_table_name
    queue_url       = aws_sqs_queue.processing.id
    dlq_url         = aws_sqs_queue.processing_dlq.id
    cool_version    = var.cool_version
    cool_ami_id     = var.cool_ami_id
    instance_type   = var.instance_type
    log_group_name                  = aws_cloudwatch_log_group.worker.name
    metrics_namespace               = "RentReadyVision/Processing"
    queue_visibility_timeout        = var.queue_visibility_timeout_seconds
    queue_max_receive_count         = var.queue_max_receive_count
    processing_lease_seconds        = var.queue_visibility_timeout_seconds + 300
    repository_url                  = var.repository_url
    git_ref                         = var.git_ref
  })

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = var.root_volume_size_gib
  }

  tags = merge(local.common_tags, { Name = "${local.prefix}-cool-worker" })

  depends_on = [
    aws_iam_role_policy.cool_worker,
    aws_iam_role_policy_attachment.ssm,
    aws_sqs_queue_redrive_allow_policy.processing_dlq
  ]
}
