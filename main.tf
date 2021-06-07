terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = var.project_tags
  }
}

data "aws_caller_identity" "current" {}

#--- Storage
resource "aws_s3_bucket" "posts_storage" {
  bucket_prefix = "fs-raw-storage"
  acl           = "private"
}

#--- Credentials
resource "aws_kms_key" "api_lock" {
  description             = "This key is used to encrypt API keys."
  deletion_window_in_days = 7
}

resource "aws_ssm_parameter" "twitter_api_key" {
  name        = "/${var.project_tags.Environment}/apikeys/twitter"
  description = "Twitter API Key"
  type        = "SecureString"
  value       = var.api_key_twitter
  key_id      = aws_kms_key.api_lock.key_id
}

#--- Virtual Network
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "3.1.0"

  name = "fs-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${var.region}a", "${var.region}b", "${var.region}c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway = false
}

#--- ECS
resource "aws_ecr_repository" "ecr_repo" {
  name = "fanstats-producer"
}

# IAM
resource "aws_iam_role" "producer_role" {
  name_prefix = "fs-producer-role"
  description = "Allows the FS Producer Tasks to call AWS services on your behalf."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      },
    ]
  })
}
resource "aws_iam_policy" "producer_policy" {
  name        = "fs-producer-policy"
  description = ""

  policy = <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "comprehend:BatchDetectSentiment",
                "comprehend:BatchDetectKeyPhrases"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": "s3:PutObject",
            "Resource": "arn:aws:s3:::${aws_s3_bucket.posts_storage.id}/*"
        },
        {
            "Effect": "Allow",
            "Action": "ssm:GetParameter",
            "Resource": "arn:aws:ssm::${data.aws_caller_identity.current.account_id}:parameter/${var.project_tags.Environment}/apikeys/*"
        },
        {
            "Effect": "Allow",
            "Action": "kms:Decrypt",
            "Resource": "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:key/${aws_kms_key.api_lock.id}"
        }
    ]
} 
EOF
}
resource "aws_iam_role_policy_attachment" "producer_role_main_attach" {
  role       = aws_iam_role.producer_role.name
  policy_arn = aws_iam_policy.producer_policy.arn
}
resource "aws_iam_role_policy_attachment" "producer_role_ecs_attach" {
  role       = aws_iam_role.producer_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
