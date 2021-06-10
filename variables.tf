#--- AWS Infrastructure
variable "region" {
  description = "AWS region to deploy this project to."
  type        = string
  default     = "eu-west-1"
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

#--- ECR
variable "image_tag" {
  description = "The tag for the container image"
  type        = string
  default     = "latest"
}
variable "ecs_env_DATA_FILE" {
  description = "The tag for the container image"
  type        = string
  default     = "nba.yaml"
}