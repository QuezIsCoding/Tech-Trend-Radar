variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (dev, prod)"
  type        = string
  default     = "prod"
}

variable "recipient_email" {
  description = "Email address to receive the trend digest"
  type        = string
  # Set via TF_VAR_recipient_email or GitHub Actions secret
}

variable "sender_email" {
  description = "SES-verified sender email address"
  type        = string
  # Must be verified in SES — see README
}

variable "groq_api_key" {
  description = "Groq API key (stored in SSM SecureString)"
  type        = string
  sensitive   = true
  # Set via TF_VAR_groq_api_key or GitHub Actions secret
}

variable "schedule_expression" {
  description = "EventBridge cron schedule (UTC). Default = every 2 days at 8am UTC"
  type        = string
  default     = "cron(0 8 */2 * ? *)"
}

variable "ecr_image_uri" {
  description = "Full ECR image URI (set by CI/CD pipeline)"
  type        = string
  # e.g. 123456789.dkr.ecr.us-east-1.amazonaws.com/tech-trend-radar:latest
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 120
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 256
}
