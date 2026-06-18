# 📡 Tech Trend Radar

> An automated AI-powered intelligence tool that scrapes the hottest tech trends from across the internet and delivers a curated digest to your inbox every 2 days.

[![CI](https://github.com/QuezIsCoding/Tech-Trend-Radar/actions/workflows/ci.yml/badge.svg)](https://github.com/QuezIsCoding/Tech-Trend-Radar/actions/workflows/ci.yml)
[![Deploy](https://github.com/QuezIsCoding/Tech-Trend-Radar/actions/workflows/deploy.yml/badge.svg)](https://github.com/QuezIsCoding/Tech-Trend-Radar/actions/workflows/deploy.yml)
![AWS](https://img.shields.io/badge/AWS-Lambda%20%7C%20SES%20%7C%20ECR-orange?logo=amazon-aws)
![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC?logo=terraform)
![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)

---

## Architecture

```
EventBridge (cron every 2 days)
        │
        ▼
  AWS Lambda (Container)
        │
        ├──► Hacker News API
        ├──► GitHub Trending API
        └──► Reddit API
        │
        ▼
  Groq API (Llama 3.3 70B)
  → Trend analysis & scoring
        │
        ▼
  Amazon SES
  → HTML email digest
        │
        ▼
     📧 You
```

**AWS Services:** Lambda · EventBridge · SES · ECR · SSM Parameter Store · IAM · CloudWatch  
**CI/CD:** GitHub Actions (lint → test → plan → build → deploy)  
**IaC:** Terraform  
**AI:** Groq API (Llama 3.3 70B — free tier)

---

## Features

- 🕷️ **Multi-source scraping** — Hacker News, GitHub Trending, Reddit (r/programming, r/devops, r/MachineLearning, r/aws, r/webdev)
- 🤖 **LLM analysis** — Groq Llama 3 identifies "get in now" signals, not just what's popular
- 📧 **Rich HTML email** — clean dark-theme digest with trend cards and signal ratings
- ⏰ **Fully automated** — EventBridge triggers every 2 days, zero manual intervention
- 🐳 **Containerized Lambda** — Docker image deployed to ECR for reproducibility
- 🔒 **Secrets management** — Groq API key stored in SSM Parameter Store (SecureString)
- 🧪 **Full test suite** — pytest with mocked AWS + Groq calls
- 🚀 **GitOps CI/CD** — PRs get a Terraform plan comment; merges auto-deploy

---

## Project Structure

```
tech-trend-radar/
├── .github/
│   └── workflows/
│       ├── ci.yml          # Lint, test, terraform plan (on PR)
│       └── deploy.yml      # Build image + terraform apply (on merge)
├── lambda/
│   ├── src/
│   │   └── handler.py      # Core logic: scrape → analyze → email
│   ├── Dockerfile          # Multi-stage container build
│   └── requirements.txt
├── terraform/
│   ├── main.tf             # Provider + S3 backend
│   ├── variables.tf        # All configurable inputs
│   ├── ecr.tf              # ECR repository + lifecycle policy
│   ├── iam.tf              # Lambda execution role + policies
│   ├── lambda.tf           # Lambda, EventBridge, SSM, CloudWatch
│   └── outputs.tf
├── tests/
│   └── test_handler.py     # Unit tests (pytest)
├── pyproject.toml          # Ruff + pytest config
└── README.md
```

---

## Prerequisites

- AWS account with CLI configured (`aws configure`)
- Terraform >= 1.7.0
- Docker
- Python 3.12
- [Groq API key](https://console.groq.com) (free)
- SES sender email verified in your AWS account

---

## Deployment Guide

### 1. Verify your sender email in SES

```bash
aws ses verify-email-identity --email-address your-sender@email.com
```

> ⚠️ If your AWS account is in SES sandbox mode, also verify your recipient email.  
> To exit sandbox: AWS Console → SES → Account dashboard → Request production access.

### 2. Create Terraform remote state infrastructure

```bash
# Create S3 bucket for state
aws s3api create-bucket \
  --bucket your-terraform-state-bucket \
  --region us-east-1

aws s3api put-bucket-versioning \
  --bucket your-terraform-state-bucket \
  --versioning-configuration Status=Enabled

# Create DynamoDB table for state locking
aws dynamodb create-table \
  --table-name terraform-state-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### 3. Update `terraform/main.tf` backend

Replace `your-terraform-state-bucket` with your actual bucket name.

### 4. Bootstrap ECR (first deploy only)

The ECR repository must exist before the Lambda can reference an image. On first deploy, comment out `lambda.tf` temporarily, apply ECR only, push an image, then apply everything.

Or use the helper script:

```bash
# 1. Init and apply just ECR
cd terraform
terraform init
terraform apply -target=aws_ecr_repository.lambda_repo

# 2. Build and push initial image
ECR_URL=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin "$ECR_URL"

docker build -t "$ECR_URL:latest" ../lambda/
docker push "$ECR_URL:latest"

# 3. Apply everything
terraform apply \
  -var="recipient_email=you@email.com" \
  -var="sender_email=sender@email.com" \
  -var="groq_api_key=gsk_xxxx" \
  -var="ecr_image_uri=$ECR_URL:latest"
```

### 5. Set GitHub Actions secrets

In your repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `AWS_REGION` | e.g. `us-east-1` |
| `RECIPIENT_EMAIL` | Where digests are delivered |
| `SENDER_EMAIL` | Your SES-verified sender |
| `GROQ_API_KEY` | Your Groq API key |
| `ECR_REPOSITORY_URL` | Output from terraform (`ecr_repository_url`) |

### 6. Push to main — CI/CD takes over

```bash
git add .
git commit -m "feat: initial deployment"
git push origin main
```

GitHub Actions will:
1. Lint your Python with Ruff
2. Run the test suite
3. Build your Docker image and push to ECR
4. Run `terraform apply` to wire everything up

---

## Running Locally

```bash
# Install dependencies
cd lambda
pip install -r requirements.txt
pip install pytest pytest-mock ruff

# Run tests
pytest tests/ -v

# Lint
ruff check lambda/src/

# Invoke locally (requires AWS credentials + real env vars)
export RECIPIENT_EMAIL=you@email.com
export SENDER_EMAIL=sender@email.com
export GROQ_API_KEY_PARAM=/tech-trend-radar/groq-api-key
python -c "from lambda.src.handler import lambda_handler; lambda_handler({}, {})"
```

---

## Customization

| What | Where | How |
|------|-------|-----|
| Schedule | `terraform/variables.tf` → `schedule_expression` | Any EventBridge cron |
| Number of items scraped | Lambda env vars `HN_TOP_N`, `REDDIT_TOP_N`, `GITHUB_TOP_N` | Set in `lambda.tf` |
| Add a new source | `lambda/src/handler.py` | Add a `fetch_*()` function and include in `raw_data` |
| Change LLM model | `handler.py` → `analyze_with_groq()` | Swap `llama-3.3-70b-versatile` for any Groq-supported model |
| Email styling | `handler.py` → `build_email_html()` | Edit the inline HTML/CSS |

---

## CI/CD Pipeline

```
Pull Request                    Merge to main
──────────────────────          ─────────────────────────────
✅ Ruff lint                    ✅ Ruff lint
✅ pytest suite                 ✅ pytest suite
✅ terraform validate           🐳 docker build + push to ECR
💬 terraform plan on PR         🏗️  terraform apply
```

---

## Cost Estimate

Running every 2 days (~15x/month):

| Service | Cost |
|---------|------|
| Lambda | ~$0.00 (free tier) |
| EventBridge | ~$0.00 (free tier) |
| SES | ~$0.002 (15 emails) |
| ECR | ~$0.01 (storage) |
| SSM Parameter Store | ~$0.00 |
| **Groq API** | **$0.00 (free tier)** |
| **Total** | **< $0.05/month** |

---

## License

MIT — clone it, fork it, make it yours.
