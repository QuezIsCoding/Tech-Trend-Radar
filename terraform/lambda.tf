# ── SSM Parameter — Groq API Key ──────────────────────────────────────────────
resource "aws_ssm_parameter" "groq_api_key" {
  name        = "/tech-trend-radar/groq-api-key"
  description = "Groq API key for LLM trend analysis"
  type        = "SecureString"
  value       = var.groq_api_key

  lifecycle {
    ignore_changes = [value]  # Allow manual rotation without Terraform drift
  }
}

# ── CloudWatch Log Group ───────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/tech-trend-radar"
  retention_in_days = 14
}

# ── Lambda Function (container image) ─────────────────────────────────────────
resource "aws_lambda_function" "trend_radar" {
  function_name = "tech-trend-radar"
  description   = "Scrapes tech trends and sends email digest via Groq + SES"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = var.ecr_image_uri
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  environment {
    variables = {
      RECIPIENT_EMAIL    = var.recipient_email
      SENDER_EMAIL       = var.sender_email
      GROQ_API_KEY_PARAM = aws_ssm_parameter.groq_api_key.name
      HN_TOP_N           = "30"
      GITHUB_TOP_N       = "10"
      REDDIT_TOP_N       = "15"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_cloudwatch_log_group.lambda_logs,
  ]
}

# ── EventBridge Rule (every 2 days) ───────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "tech-trend-radar-schedule"
  description         = "Trigger Tech Trend Radar every 2 days"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "TechTrendRadarLambda"
  arn       = aws_lambda_function.trend_radar.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.trend_radar.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.trend_radar.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.trend_radar.arn
}

output "next_trigger" {
  description = "EventBridge schedule expression"
  value       = aws_cloudwatch_event_rule.schedule.schedule_expression
}
