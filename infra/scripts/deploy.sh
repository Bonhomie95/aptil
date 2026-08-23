#!/usr/bin/env bash
# Deploy on the VPS. Run from the repo root after `git pull`.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

if [[ ! -f .env ]]; then
  echo "ERROR: .env is missing. Copy .env.example and fill it in." >&2
  exit 1
fi

# Fail fast on placeholder secrets rather than booting an insecure production
# stack (the API refuses to start on these too, but a clear message here is
# cheaper than reading container logs).
# MINIO_ROOT_USER is in this list because it was not, once: production booted
# with only MINIO_ROOT_PASSWORD set and the failure surfaced as an unhealthy
# container looping "Missing credential environment variable" — several layers
# away from the actual cause.
for var in SECRET_KEY CREDENTIAL_ENCRYPTION_KEY \
           MINIO_ROOT_USER MINIO_ROOT_PASSWORD MINIO_BUCKET \
           APP_DOMAIN; do
  value="$(grep -E "^${var}=" .env | cut -d= -f2- || true)"
  if [[ -z "$value" || "$value" == change-me* ]]; then
    echo "ERROR: ${var} is unset or still a placeholder in .env" >&2
    case "$var" in
      APP_DOMAIN)
        echo "       Set it to your bare domain, e.g. APP_DOMAIN=example.com" >&2
        echo "       Caddy issues the TLS certificate for that name." >&2
        ;;
      MINIO_*)
        echo "       These are the S3 credentials despite the MINIO_ prefix." >&2
        echo "       For Cloudflare R2: MINIO_ROOT_USER is the Access Key ID," >&2
        echo "       MINIO_ROOT_PASSWORD the Secret Access Key, MINIO_ENDPOINT" >&2
        echo "       the account endpoint, MINIO_REGION=auto, MINIO_SECURE=true." >&2
        echo "       See docs/storage-s3.md." >&2
        ;;
    esac
    exit 1
  fi
done

# Caddy reads the domain from its own environment, not from .env, so export it.
# Quotes are stripped because APP_DOMAIN="example.com" in .env is a reasonable
# thing to write and Caddy would ask a CA for a certificate including them.
APP_DOMAIN="$(grep -E '^APP_DOMAIN=' .env | cut -d= -f2-)"
APP_DOMAIN="${APP_DOMAIN%\"}"
APP_DOMAIN="${APP_DOMAIN#\"}"
APP_DOMAIN="${APP_DOMAIN%\'}"
APP_DOMAIN="${APP_DOMAIN#\'}"
export APP_DOMAIN

echo "==> Building and starting production stack"
$COMPOSE up -d --build --wait --wait-timeout 300

# MongoDB is schemaless — no migration step. Beanie creates collections + indexes
# on first init. Seed the default plans (idempotent, and required: new accounts
# are provisioned onto the free plan).
echo "==> Seeding default plans"
$COMPOSE exec -T api python -m scripts.seed

echo "==> Health"
$COMPOSE exec -T api curl -fsS http://127.0.0.1:8000/health/ready

echo
echo "==> Done. Services:"
$COMPOSE ps
