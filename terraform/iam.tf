# ── Lambda Execution Role ──────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_exec" {
  name = "tech-trend-radar-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# ── CloudWatch Logs ────────────────────────────────────────────────────────────
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ── SES Send Permission ────────────────────────────────────────────────────────
resource "aws_iam_role_policy" "lambda_ses" {
  name = "tech-trend-radar-ses-policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendEmail", "ses:SendRawEmail"]
      Resource = "*"
      Condition = {
        StringEquals = {
          "ses:FromAddress" = var.sender_email
        }
      }
    }]
  })
}

# ── SSM Parameter Store (Groq API key) ────────────────────────────────────────
resource "aws_iam_role_policy" "lambda_ssm" {
  name = "tech-trend-radar-ssm-policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/tech-trend-radar/*"
    }, {
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = "*"
      Condition = {
        StringEquals = {
          "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com"
        }
      }
    }]
  })
}
