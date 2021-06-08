#--- AWS Infrastructure
variable "region" {
  description = "AWS region to deploy this project to."
  type        = string
  default     = "us-east-1"
}

variable "project_tags" {
  description = "Tags to apply to resources created by this module"
  type        = map(string)
  default = {
    Terraform   = "true"
    Project     = "Fanstats.ai"
    Environment = "dev"
  }
}

#--- API Keys
variable "api_key_twitter" {
  description = "The Twitter API Key"
  type        = string
  default     = "1234"
}