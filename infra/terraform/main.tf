provider "aws" { region = var.aws_region }
data "aws_caller_identity" "current" {}
locals { prefix = "${var.project_name}-${var.environment}" }

resource "aws_s3_bucket" "media" {
  bucket = "${local.prefix}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id
  block_public_acls = true
  ignore_public_acls = true
  block_public_policy = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}

resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  cors_rule {
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_origins = var.frontend_origins
    allowed_headers = ["*"]
    expose_headers = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    id = "expire-prototype-video"
    status = "Enabled"
    filter { prefix = "inspections/" }
    expiration { days = 30 }
  }
}

resource "aws_dynamodb_table" "app" {
  name = local.prefix
  billing_mode = "PAY_PER_REQUEST"
  hash_key = "PK"
  range_key = "SK"
  attribute { name = "PK"; type = "S" }
  attribute { name = "SK"; type = "S" }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}
