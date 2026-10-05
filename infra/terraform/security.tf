# Only use this route when Terraform owns the bucket. For a preexisting/shared
# bucket use scripts/configure_step40_security.py --apply to merge statements.
resource "aws_s3_bucket_ownership_controls" "media" {
  count  = var.manage_data_resources ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_policy" "media_security" {
  count  = var.manage_data_resources ? 1 : 0
  bucket = aws_s3_bucket.media[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "RentReadyDenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.media[0].arn, "${aws_s3_bucket.media[0].arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "RentReadyDenyStalePresignedRequests"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = ["${aws_s3_bucket.media[0].arn}/rentready/inspections/*", "${aws_s3_bucket.media[0].arn}/inspections/*"]
        Condition = {
          StringEquals       = { "s3:authType" = "REST-QUERY-STRING" }
          NumericGreaterThan = { "s3:signatureAge" = "900000" }
        }
      }
    ]
  })
}
