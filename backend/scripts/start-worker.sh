#!/usr/bin/env bash
# Runs four Celery consumers instead of one so slow background work can never
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
#   - `apply`      : every submit_application run — clicking "Apply"/"Apply
#                    top N", the post-verification requeue, and the periodic
#                    apply sweep all land here. Its own queue for two reasons:
#                    it's real Playwright/Chromium work (a different resource
#                    profile than interactive's plain HTTP calls), and without
#                    this split "Apply" queued FIFO behind the sourcing/
#                    matching backlog on the default queue and could spin
#                    forever with nothing ever actually submitted.
#   - `celery`     : everything else — the periodic bulk sweeps (sourcing,
#                    matching, tailoring, discovery, scheduler) — the default
#                    queue.
set -euo pipefail

celery -A app.workers.celery_app.celery worker \
  -Q critical -n critical@%h --concurrency=1 --loglevel=info &
CRITICAL_PID=$!

celery -A app.workers.celery_app.celery worker \
  -Q interactive -n interactive@%h --concurrency=2 --loglevel=info &
INTERACTIVE_PID=$!

celery -A app.workers.celery_app.celery worker \
  -Q apply -n apply@%h --concurrency=2 --loglevel=info &
APPLY_PID=$!

celery -A app.workers.celery_app.celery worker \
  -Q celery -n default@%h --concurrency=2 --loglevel=info &
DEFAULT_PID=$!

term() {
  kill -TERM "$CRITICAL_PID" "$INTERACTIVE_PID" "$APPLY_PID" "$DEFAULT_PID" 2>/dev/null || true
  wait || true
}
trap term TERM INT

# If any consumer dies, bring the whole process down so the platform restarts
# it — a silently-dead consumer would reintroduce the blocking bug this
# script exists to fix.
wait -n "$CRITICAL_PID" "$INTERACTIVE_PID" "$APPLY_PID" "$DEFAULT_PID"
term
exit 1
