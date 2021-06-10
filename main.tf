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
resource "aws_security_group" "app-layer" {
  name        = "App Layer"
  description = "Applies to application backend-layer instances."
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}

#--- Elastic Container Service
resource "aws_ecr_repository" "ecr_repo" {
  name = "fanstats-producer"
}

# IAM
resource "aws_iam_role" "producer_role" {
  name_prefix = "fs-producer-ecs-role"
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

# ECS
resource "aws_ecs_task_definition" "producer" {
  family = "fs-producer"
  cpu    = 256
  memory = 512
  container_definitions = jsonencode([
    {
      name  = "fanstats-producer"
      image = "${aws_ecr_repository.ecr_repo.repository_url}:${var.image_tag}"
      environment = [
        {
          name  = "DATA_FILE"
          value = var.ecs_env_DATA_FILE
        },
        {
          name  = "STORAGE_BUCKET"
          value = aws_s3_bucket.posts_storage.id
        }
      ]
      secrets = [
        {
          name      = "TWITTER_BEARER_TOKEN",
          valueFrom = aws_ssm_parameter.twitter_api_key.arn
        }
      ]
    }
  ])
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]

  execution_role_arn = aws_iam_role.producer_role.arn
  task_role_arn      = aws_iam_role.producer_role.arn
}
resource "aws_ecs_cluster" "cluster" {
  name = "FanStats-Producer-Cluster"
}

# EventBridge
resource "aws_iam_role" "ecs_events" {
  name = "ecs_events"

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "",
      "Effect": "Allow",
      "Principal": {
        "Service": "events.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
}
resource "aws_iam_role_policy" "ecs_events_run_task_with_any_role" {
  name = "ecs_events_run_task_with_any_role"
  role = aws_iam_role.ecs_events.id

  policy = <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": "ecs:RunTask",
            "Resource": "${replace(aws_ecs_task_definition.producer.arn, "/:\\d+$/", ":*")}"
        }
    ]
}
EOF
}

resource "aws_cloudwatch_event_rule" "at_midnight" {
  name                = "FSAI-TriggerProducers"
  description         = "Triggers FanStats Team Producer tasks."
  schedule_expression = "cron(0 5 ? * * *)"
}
resource "aws_cloudwatch_event_target" "ecs_run_task" {
  target_id = "run-task-every-midnight"
  arn       = aws_ecs_cluster.cluster.arn
  rule      = aws_cloudwatch_event_rule.at_midnight.name
  role_arn  = aws_iam_role.ecs_events.arn

  ecs_target {
    task_count          = 1
    task_definition_arn = aws_ecs_task_definition.producer.arn

    launch_type      = "FARGATE"
    platform_version = "LATEST"

    network_configuration {
      assign_public_ip = true
      security_groups = [
        aws_security_group.app-layer.id
      ]
      subnets = [
        module.vpc.public_subnets[0],
        module.vpc.public_subnets[1],
        module.vpc.public_subnets[2],
      ]
    }
  }
}

#--- Analytics

# IAM
resource "aws_iam_policy" "glue_policy" {
  name        = "fs-glue-policy"
  description = ""

  policy = <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject"
            ],
            "Resource": [
                "arn:aws:s3:::${aws_s3_bucket.posts_storage.id}/Twitter/*"
            ]
        }
    ]
}
EOF
}
resource "aws_iam_role" "glue_role" {
  name_prefix = "fs-producer-glue-role"
  description = "Allows FS Glue to call AWS services on your behalf."

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "",
      "Effect": "Allow",
      "Principal": {
        "Service": "glue.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
}
resource "aws_iam_role_policy_attachment" "glue_role_main_attach" {
  role       = aws_iam_role.glue_role.name
  policy_arn = aws_iam_policy.glue_policy.arn
}
resource "aws_iam_role_policy_attachment" "glue_role_service_attach" {
  role       = aws_iam_role.glue_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# Glue
resource "aws_glue_catalog_database" "main" {
  name = "fanstatsai"
}
resource "aws_glue_crawler" "twitter" {
  database_name = aws_glue_catalog_database.main.name
  name          = "FanStats-Twitter"
  role          = aws_iam_role.glue_role.arn

  schedule = "cron(30 5 ? * * *)"

  s3_target {
    path = "s3://${aws_s3_bucket.posts_storage.id}/Twitter/"
  }
}