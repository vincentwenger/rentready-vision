# Step 53 release: exact-object S3 download permissions.
# Existing artifact permissions remain unchanged.

resource "aws_iam_role_policy" "api_step53_artifact_read" {
  name = "step53-release-artifact-read"
  role = var.api_runtime_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadStep53ApiArtifact"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::rentready-vision-dev-081087819788/deployments/api/step49/051fd98556025825f84cc3198e5a5ae974ddf653/api-dc8b886d0a0d24123d85370db79461687d9a9160b13ea4d1ef14592f0c7694d4.zip"
      }
    ]
  })
}

resource "aws_iam_role_policy" "worker_step53_artifact_read" {
  name = "step53-release-artifact-read"
  role = aws_iam_role.cool_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadStep53WorkerArtifact"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::rentready-vision-dev-081087819788/deployments/cool-worker/step49-051fd9855602/rentready-vision-cool-worker-step49-051fd9855602.tar.gz"
      }
    ]
  })
}
