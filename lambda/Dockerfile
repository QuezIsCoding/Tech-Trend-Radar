# ── Build stage ───────────────────────────────────────────────────────────────
FROM public.ecr.aws/lambda/python:3.12 AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --target /build/deps -r requirements.txt

# ── Final stage ───────────────────────────────────────────────────────────────
FROM public.ecr.aws/lambda/python:3.12

# Copy installed dependencies
COPY --from=builder /build/deps ${LAMBDA_TASK_ROOT}

# Copy function code
COPY src/handler.py ${LAMBDA_TASK_ROOT}/handler.py

# Lambda handler entrypoint
CMD ["handler.lambda_handler"]
