#!/usr/bin/env bash
# Runs three Celery consumers instead of one so slow background work can never
# block something the user is actively waiting on, in either direction:
#   - `critical`   : email.send only, its own reserved slot. A slow Playwright
#                    apply job must never delay a verification code or reset
#                    email behind it in the same worker pool.
#   - `interactive`: on-demand, user-triggered sourcing (the "Find new
#                    matches" button, a target-titles change, right after a
#                    CV upload) — see the source_for_user call sites tagged
#                    "Dedicated queue" in jobs.py, onboarding.py, cv_parsing.py.
#                    Without this, a click here queues FIFO behind the bulk
#                    per-user sweep below and can wait hours once the user
#                    base outgrows what the default queue can clear per sweep
#                    interval.
#   - `celery`     : everything else — the periodic bulk sweeps (sourcing,
#                    matching, apply, tailoring, discovery, scheduler) — the
#                    default queue.
set -euo pipefail

celery -A app.workers.celery_app.celery worker \
  -Q critical -n critical@%h --concurrency=1 --loglevel=info &
CRITICAL_PID=$!

celery -A app.workers.celery_app.celery worker \
  -Q interactive -n interactive@%h --concurrency=2 --loglevel=info &
INTERACTIVE_PID=$!

celery -A app.workers.celery_app.celery worker \
  -Q celery -n default@%h --concurrency=2 --loglevel=info &
DEFAULT_PID=$!

term() {
  kill -TERM "$CRITICAL_PID" "$INTERACTIVE_PID" "$DEFAULT_PID" 2>/dev/null || true
  wait || true
}
trap term TERM INT

# If any consumer dies, bring the whole process down so the platform restarts
# it — a silently-dead consumer would reintroduce the blocking bug this
# script exists to fix.
wait -n "$CRITICAL_PID" "$INTERACTIVE_PID" "$DEFAULT_PID"
term
exit 1
