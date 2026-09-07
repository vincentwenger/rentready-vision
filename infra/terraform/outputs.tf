output "aws_region" {
  value = var.aws_region
}

output "s3_bucket" {
  value = local.s3_bucket_name
}

output "ddb_table" {
  value = local.dynamodb_table_name
}

output "processing_queue_url" {
  value = aws_sqs_queue.processing.id
}

output "processing_dlq_url" {
  value = aws_sqs_queue.processing_dlq.id
}

output "processing_producer_policy_arn" {
  value       = aws_iam_policy.processing_producer.arn
  description = "Attach this least-privilege policy to the API's IAM role."
}

output "worker_instance_id" {
  value = aws_instance.cool_worker.id
}

output "worker_instance_type" {
  value = aws_instance.cool_worker.instance_type
}

output "cool_ami_id" {
  value = aws_instance.cool_worker.ami
}

output "cool_version" {
  value = var.cool_version
}

output "session_manager_command" {
  value = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.cool_worker.id}"
}

output "worker_git_ref" {
  value = var.git_ref
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.worker.name
}

output "cloudwatch_metrics_namespace" {
  value = "RentReadyVision/Processing"
}
