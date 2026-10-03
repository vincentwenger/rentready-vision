variable "aws_region" {
  description = "AWS Region that already contains the RentReady S3 bucket."
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  type    = string
  default = "rentready-vision"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "s3_bucket_name" {
  description = "Existing RentReady bucket name, or the name Terraform should create when manage_data_resources is true."
  type        = string
}

variable "dynamodb_table_name" {
  description = "Existing RentReady DynamoDB table, or the name Terraform should create when manage_data_resources is true."
  type        = string
  default     = "rentready-vision-dev"
}

variable "manage_data_resources" {
  description = "Create and manage the S3 bucket and DynamoDB table. Leave false for resources that already exist."
  type        = bool
  default     = false
}

variable "frontend_origins" {
  type    = list(string)
  default = ["http://localhost:8000", "http://localhost:5173"]
}


variable "worker_artifact_s3_bucket" {
  description = "S3 bucket containing the immutable worker artifact. Null reuses s3_bucket_name."
  type        = string
  default     = null
  nullable    = true
}

variable "worker_artifact_s3_key" {
  description = "Exact versioned S3 key of the rentready-vision-cool-worker tar.gz artifact."
  type        = string
  validation {
    condition     = can(regex("^deployments/cool-worker/[^/]+/rentready-vision-cool-worker-[^/]+\\.tar\\.gz$", var.worker_artifact_s3_key))
    error_message = "Use a versioned deployments/cool-worker/<version>/rentready-vision-cool-worker-<version>.tar.gz key."
  }
}

variable "worker_artifact_sha256" {
  description = "SHA-256 of the exact worker artifact; bootstrap refuses any mismatch."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{64}$", var.worker_artifact_sha256))
    error_message = "worker_artifact_sha256 must be a 64-character SHA-256 hex digest."
  }
}

variable "worker_artifact_version" {
  description = "Immutable artifact version, normally the release tag or short Git commit."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.worker_artifact_version))
    error_message = "worker_artifact_version may contain only letters, digits, '.', '_' and '-'."
  }
}

variable "cool_ami_id" {
  description = "Region-specific AMI ID shown by the subscribed OpenCV COOL 3.1 Marketplace product."
  type        = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]+$", var.cool_ami_id))
    error_message = "cool_ami_id must be the AMI ID copied from the subscribed COOL Marketplace launch page."
  }
}

variable "cool_version" {
  description = "Marketplace COOL product version selected at launch."
  type        = string
  default     = "3.1"
}

variable "instance_type" {
  description = "Official benchmark configuration is m8g.4xlarge."
  type        = string
  default     = "m8g.4xlarge"
  validation {
    condition     = can(regex("^(c8g|m8g|r8g)\\.", var.instance_type))
    error_message = "Use a Graviton4 c8g, m8g, or r8g instance type."
  }
}

variable "vpc_id" {
  description = "VPC for the worker security group."
  type        = string
}

variable "subnet_id" {
  description = "Subnet in the same Region as the RentReady data resources. It needs outbound HTTPS through NAT, VPC endpoints, or an internet gateway."
  type        = string
}

variable "associate_public_ip_address" {
  description = "A public IP is optional; no inbound security-group rules or SSH key are created."
  type        = bool
  default     = false
}

variable "root_volume_size_gib" {
  type    = number
  default = 100
  validation {
    condition     = var.root_volume_size_gib >= 30
    error_message = "Use at least 30 GiB for video processing."
  }
}

variable "queue_visibility_timeout_seconds" {
  type    = number
  default = 1800
}

variable "queue_max_receive_count" {
  type    = number
  default = 5
}

variable "bedrock_model_arns" {
  description = "Exact Bedrock foundation-model or inference-profile ARNs the worker may invoke. Empty disables Bedrock permission until a model is chosen."
  type        = list(string)
  default     = []
}

variable "s3_video_retention_days" {
  description = "Step 39 retention in days; applies only to original videos or incomplete uploads."
  type        = number
  default     = 30
  validation {
    condition     = var.s3_video_retention_days >= 1 && floor(var.s3_video_retention_days) == var.s3_video_retention_days
    error_message = "Retention days must be a positive integer."
  }
}

variable "s3_noncurrent_video_retention_days" {
  description = "Step 39 retention in days; applies only to original videos or incomplete uploads."
  type        = number
  default     = 30
  validation {
    condition     = var.s3_noncurrent_video_retention_days >= 1 && floor(var.s3_noncurrent_video_retention_days) == var.s3_noncurrent_video_retention_days
    error_message = "Retention days must be a positive integer."
  }
}

variable "s3_abort_multipart_days" {
  description = "Step 39 retention in days; applies only to original videos or incomplete uploads."
  type        = number
  default     = 7
  validation {
    condition     = var.s3_abort_multipart_days >= 1 && floor(var.s3_abort_multipart_days) == var.s3_abort_multipart_days
    error_message = "Retention days must be a positive integer."
  }
}
