"""Transactional email delivery, off the request path.

Sending inline cost ~8s per signup against a real relay — the user watched a
dead button while smtplib negotiated TLS. Worse, a slow relay stalled a request
worker for the whole round trip.

Delivery here is durable in a way an inline send never was: a task that fails is
retried with backoff instead of being logged and forgotten.

Note on what travels: the message body carries the verification / reset link,
and therefore the plaintext token, through the broker. That is unavoidable —
only the SHA-256 of the token is stored, so the worker could not rebuild the
link itself. It is bounded (single-use, 24h for verification, 60m for a reset)
and Redis is bound to loopback in every shipped compose file; keep it that way.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.email import send_email_sync
from app.workers.celery_app import celery

log = get_logger(__name__)

# 1m, 4m, 15m. A verification link is worth persisting through a relay outage,
# and by the last attempt the user has probably clicked "resend" anyway.
_RETRY_DELAYS = (60, 240, 900)


@celery.task(
    name="email.send",
    bind=True,
    max_retries=len(_RETRY_DELAYS),
    acks_late=True,
    reject_on_worker_lost=True,
    # Own queue, consumed by a dedicated worker process (see
    # scripts/start-worker.sh) — a verification code must never wait behind a
    # multi-minute Playwright apply job on the shared worker pool.
    queue="critical",
)
def send_email_task(
    self, to: str, subject: str, body: str, html_body: str | None = None
) -> dict:
    try:
        send_email_sync(to, subject, body, html_body)
    except Exception as exc:  # noqa: BLE001 - retry, then give up loudly
        attempt = self.request.retries
        log.warning(
            "email_send_retry", to=to, subject=subject, attempt=attempt, error=str(exc)
        )
        try:
            # Clamped: the body also runs on the attempt AFTER the last retry
            # (retries == max_retries), so indexing straight in raised
            # IndexError there — the task then died on that instead of on
            # MaxRetriesExceeded, and never logged that it had given up.
            countdown = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            log.error("email_send_gave_up", to=to, subject=subject)
            return {"sent": False}
    return {"sent": True}
