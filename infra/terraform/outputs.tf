output "s3_bucket" { value = aws_s3_bucket.media.bucket }
output "ddb_table" { value = aws_dynamodb_table.app.name }
