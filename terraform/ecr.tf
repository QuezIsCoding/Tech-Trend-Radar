# ── ECR Repository ─────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "lambda_repo" {
  name                 = "tech-trend-radar"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# Keep last 10 images, clean up older ones automatically
resource "aws_ecr_lifecycle_policy" "lambda_repo" {
  repository = aws_ecr_repository.lambda_repo.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

output "ecr_repository_url" {
  description = "ECR repository URL (used in CI/CD)"
  value       = aws_ecr_repository.lambda_repo.repository_url
}
