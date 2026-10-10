# Step 54 - Exact-object access to the report rectangle deployment.
#
# This policy already exists in AWS following Step 54.19C.
# Import it into Terraform state before any Terraform apply.
# Preserve all existing API and worker permissions.

resource "aws_iam_role_policy" "api_step54_artifact_read" {
  name = "step54-release-artifact-read"
  role = var.api_runtime_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadStep54ApiArtifact"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::rentready-vision-dev-081087819788/deployments/api/step54/f1d33e5c57ff7ec48b1babc4c12be3d627ec3117/step54-api-patch-17b5c81fec4781b6.zip"
      }
    ]
  })
}
