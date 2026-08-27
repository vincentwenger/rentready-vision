variable "aws_region" { type = string; default = "us-west-2" }
variable "project_name" { type = string; default = "rentready-vision" }
variable "environment" { type = string; default = "dev" }
variable "frontend_origins" {
  type = list(string)
  default = ["http://localhost:8000", "http://localhost:5173"]
}
