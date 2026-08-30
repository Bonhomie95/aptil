#!/usr/bin/env bash
# Runs two Celery consumers instead of one so a slow Playwright apply job can
# never block a time-sensitive email (verification codes, password resets)
# behind it in the same worker pool:
#   - `critical`: email.send only, its own reserved slot.
#   - `celery`  : everything else (cv_parsing, apply, discovery, sourcing,
#                 tailoring, scheduler) — the default queue.
set -euo pipefail

celery -A app.workers.celery_app.celery worker \
  -Q critical -n critical@%h --concurrency=1 --loglevel=info &
CRITICAL_PID=$!

celery -A app.workers.celery_app.celery worker \
  -Q celery -n default@%h --concurrency=2 --loglevel=info &
DEFAULT_PID=$!

term() {
  kill -TERM "$CRITICAL_PID" "$DEFAULT_PID" 2>/dev/null || true
  wait || true
}
trap term TERM INT

# If either consumer dies, bring the whole process down so the platform
# restarts it — a silently-dead critical worker would reintroduce the
# blocking bug this script exists to fix.
wait -n "$CRITICAL_PID" "$DEFAULT_PID"
term
exit 1
