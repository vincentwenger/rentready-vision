# For Terraform-owned buckets only. For an existing shared bucket with
# manage_data_resources=false, use scripts/configure_s3_lifecycle.py to merge
# rules without taking ownership of the complete lifecycle configuration.
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  count  = var.manage_data_resources ? 1 : 0
  bucket = aws_s3_bucket.media[0].id

  dynamic "rule" {
    for_each = { current = "rentready/inspections/", legacy = "inspections/" }
    content {
      id     = "rentready-step39-${rule.key}-videos"
      status = "Enabled"
      filter {
        and {
          prefix = rule.value
          tags = { rentready-artifact = "original-video" }
        }
      }
      expiration {
        days = var.s3_video_retention_days
      }
      noncurrent_version_expiration {
        noncurrent_days = var.s3_noncurrent_video_retention_days
      }
    }
  }

  dynamic "rule" {
    for_each = { current = "rentready/inspections/", legacy = "inspections/" }
    content {
      id     = "rentready-step39-${rule.key}-multipart"
      status = "Enabled"
      filter { prefix = rule.value }
      abort_incomplete_multipart_upload {
        days_after_initiation = var.s3_abort_multipart_days
      }
    }
  }

  dynamic "rule" {
    for_each = { current = "rentready/inspections/", legacy = "inspections/" }
    content {
      id     = "rentready-step39-${rule.key}-delete-markers"
      status = "Enabled"
      filter { prefix = rule.value }
      expiration {
        expired_object_delete_marker = true
      }
    }
  }
}
