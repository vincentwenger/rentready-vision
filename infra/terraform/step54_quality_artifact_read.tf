# Step 54 - Frontend rectangle quality correction.
#
# Exact-object S3 read permission for the corrected frontend ZIP.
# This IAM policy was already created manually in AWS.
#
# Import the existing policy into Terraform state before any apply.
# Preserve previous API, worker and artifact permissions.

resource "aws_iam_role_policy" "api_step54_quality_artifact_read" {
  name = "step54-quality-artifact-read"
  role = var.api_runtime_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadStep54QualityArtifact"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::rentready-vision-dev-081087819788/deployments/api/step54-quality/5ebe8efe2e725cfbba703532622cdf2dba1852d3/step54-frontend-correction-ea1a5124dfaefd89.zip"
      }
    ]
  })
}
