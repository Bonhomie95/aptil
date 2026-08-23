"""Consent-based apply engine (spec points 7, 8, 11, 13).

IMPORTANT — compliance guardrails (see docs/compliance.md):
- We apply through official ATS application forms (Greenhouse, Lever, Ashby) and
  legitimate job feeds, NOT by piloting a user's logged-in LinkedIn/Indeed session.
- Where an ATS hides the form behind a sign-in, we may sign in with a credential
  the user stored for that exact site. We never create an account.
- We do NOT solve CAPTCHAs or evade bot-detection. If a site presents one, the
  application is parked in NEEDS_INFO for the user to complete themselves.
- Two-at-a-time per user, deduped by job fingerprint (never apply to the same role twice).
- Every action is written to JobApplication.events as an audit trail.
- Plan entitlements are checked and metered on every submission.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.enums import ApplicationStatus, AutomationState
from app.models.job import Job, JobApplication
from app.models.profile import Profile, SiteCredential
from app.models.user import User
from app.services import billing
from app.services.ats import get_ats_adapter
from app.workers.celery_app import celery
from app.workers.db import run_async

log = get_logger(__name__)

MAX_CONCURRENT_PER_USER = 2

# Maps an adapter's `detail` to what the user should actually do about it.
# The dashboard turns these into a specific call to action.
_ACTION_FOR = {
    "captcha_or_botcheck": "finish_manually",
    "automation_unavailable": "retry_later",
    "submit_control_not_found": "finish_manually",
    "application_form_not_recognised": "finish_manually",
    # The employer routed us to their own careers site, which has different
    # markup (often no form on the page at all). Nothing is broken and there is
    # nothing to retry — the user finishes it on the employer's site.
    "employer_hosts_own_form": "apply_on_employer_site",
    "submission_not_confirmed": "verify_manually",
    "quota_exhausted": "upgrade",
    # Sites that hide the form behind a sign-in.
    "credential_required": "add_credential",
    # We created (or already hold) an account for this site with the user's
    # managed alias; the site's verification mail hasn't been followed yet.
    # Fully automatic from here — the inbound-email pipeline finishes it.
    "verification_pending": "awaiting_email_verification",
    "signup_form_not_recognised": "add_credential",
    "credential_unreadable": "add_credential",
    "login_failed": "check_credential",
    "login_form_not_recognised": "finish_manually",
    "login_page_unreachable": "retry_later",
    "login_not_supported": "finish_manually",
    "multi_step_application": "finish_multi_step",
}

# needs_action values that require the USER to do something. Everything the
# engine resolves on its own (email verification, automatic retry) is
# deliberately NOT here, so those rows read as "pending" rather than "your
# problem". The dashboard hides this set by default — see the applications
# endpoint's `include_needs_you`.
USER_INTERVENTION_ACTIONS = frozenset({
    "finish_manually",
    "verify_manually",
    "add_credential",
    "check_credential",
    "finish_multi_step",
    "apply_on_employer_site",
    "review",
    "upgrade",
})

# Work that is already in flight and counts against the concurrency budget.
IN_FLIGHT_STATUSES = [
    ApplicationStatus.QUEUED.value,
]


def _record_event(app_row: JobApplication, kind: str, detail: str = "") -> None:
    events = list(app_row.events)
    events.append(
        {"at": datetime.now(UTC).isoformat(), "kind": kind, "detail": detail}
    )
    # Keep the audit trail bounded so a long-lived row cannot grow without limit.
    app_row.events = events[-100:]


@celery.task(
    name="apply.submit_application",
    bind=True,
    max_retries=1,
    acks_late=True,
    reject_on_worker_lost=True,
)
def submit_application(self, application_id: str) -> dict:
    try:
        return run_async(_submit_async(application_id))
    except Exception as exc:  # noqa: BLE001
        log.error("application_failed", application_id=application_id, error=str(exc))
        try:
            raise self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            # Do not leave the row stuck in QUEUED forever — surface the failure.
            run_async(_mark_failed(application_id, "The apply engine could not complete."))
            return {"status": ApplicationStatus.FAILED.value}


async def _mark_failed(application_id: str, message: str) -> None:
    app_row = await JobApplication.get(uuid.UUID(application_id))
    if app_row is None:
        return
    app_row.status = ApplicationStatus.FAILED.value
    app_row.error_message = message
    _record_event(app_row, "failed", message)
    app_row.touch()
    await app_row.save()


async def _submit_async(application_id: str) -> dict:
    app_row = await JobApplication.get(uuid.UUID(application_id))
    if app_row is None:
        return {"status": "not_found"}
    if app_row.status in (
        ApplicationStatus.SUBMITTED.value,
        ApplicationStatus.CONFIRMED.value,
    ):
        # Idempotent: a retried task must never double-submit a real application.
        return {"status": app_row.status, "detail": "already_submitted"}

    # Entitlement gate at the point of spend.
    if not await billing.can_apply(app_row.tenant_id):
        app_row.status = ApplicationStatus.NEEDS_INFO.value
        _record_event(app_row, "parked", "Monthly application quota reached")
        app_row.error_message = "Monthly application quota reached"
        app_row.touch()
        await app_row.save()
        return {"status": app_row.status, "detail": "quota_exhausted"}

    job = await Job.get(app_row.job_id)
    _record_event(app_row, "apply_started", f"ats={job.ats_type if job else 'unknown'}")

    adapter = get_ats_adapter(job.ats_type if job else None)
    if adapter is None:
        # No adapter for this host. From web-search discovery this is the common,
        # expected case: a posting on the employer's own careers site rather than
        # a known ATS. It is not an error — the job was found and is tracked; the
        # user finishes it where it lives. (We never pilot third-party sessions.)
        app_row.status = ApplicationStatus.NEEDS_INFO.value
        app_row.needs_action = "apply_on_employer_site"
        app_row.error_message = None
        _record_event(app_row, "parked", "employer_hosts_own_form")
        app_row.touch()
        await app_row.save()
        return {"status": app_row.status}

    profile = await Profile.find_one(Profile.user_id == app_row.user_id)
    credential = await _credential_for(app_row.user_id, job)

    # The adapter is async and the whole task body runs inside run_async, so we
    # await it directly. The adapter parks (needs_info) on any CAPTCHA/bot-check
    # — it never bypasses one.
    result = await adapter.apply(app_row, job, profile, credential)

    # Record what went on the form (field names + whether each took a value),
    # never the values themselves for anything sensitive.
    filled = result.get("filled")
    if isinstance(filled, dict):
        app_row.submitted_fields = {
            "name": bool(filled.get("name") or filled.get("first_name")),
            "email": bool(filled.get("email")),
            "phone": bool(filled.get("phone")),
            "resume": bool(filled.get("resume")),
            "at": datetime.now(UTC).isoformat(),
        }
    if credential is not None:
        app_row.credential_id = credential.id

    status_map = {
        "submitted": ApplicationStatus.SUBMITTED.value,
        "needs_info": ApplicationStatus.NEEDS_INFO.value,
        "failed": ApplicationStatus.FAILED.value,
    }
    app_row.status = status_map.get(result["status"], ApplicationStatus.FAILED.value)
    app_row.error_message = None
    if app_row.status == ApplicationStatus.SUBMITTED.value:
        app_row.submitted_at = datetime.now(UTC)
    if app_row.status in (
        ApplicationStatus.FAILED.value,
        ApplicationStatus.NEEDS_INFO.value,
    ):
        app_row.error_message = result.get("detail")
    # A machine-readable reason lets the dashboard offer the right next step
    # instead of a generic "needs your attention".
    app_row.needs_action = (
        _ACTION_FOR.get(result.get("detail", ""), "review")
        if app_row.status == ApplicationStatus.NEEDS_INFO.value
        else None
    )
    _record_event(app_row, result["status"], result.get("detail", ""))
    app_row.touch()
    await app_row.save()

    if app_row.status == ApplicationStatus.SUBMITTED.value:
        # Only a real submission consumes entitlement.
        await billing.increment_application_usage(app_row.tenant_id)
        await _notify_submitted(app_row, job)

    log.info("application_processed", application_id=application_id, status=app_row.status)
    return {"status": app_row.status, "detail": result.get("detail")}


async def _credential_for(user_id: uuid.UUID, job: Job | None) -> SiteCredential | None:
    """The credential for *this job's* site, never an arbitrary one.

    Picking any credential the user happens to have would hand one site's login
    to a different site.
    """
    if job is None or not job.apply_url:
        return None
    from urllib.parse import urlparse

    host = (urlparse(job.apply_url).hostname or "").lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]

    # Exact host first, then a parent-domain match (boards.greenhouse.io ->
    # greenhouse.io), so one credential can cover a provider's subdomains.
    candidates = await SiteCredential.find(SiteCredential.user_id == user_id).to_list()
    for cred in candidates:
        if cred.site_domain == host:
            return cred
    for cred in candidates:
        if host.endswith("." + cred.site_domain):
            return cred
    return None


async def _notify_submitted(app_row: JobApplication, job: Job | None) -> None:
    """Email the user that we applied on their behalf (architecture step 5)."""
    if job is None:
        return
    try:
        user = await User.get(app_row.user_id)
        if user is None:
            return
        from app.services.email import send_application_submitted_email

        await send_application_submitted_email(
            user.notification_email or user.email, job.company, job.title
        )
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        log.warning("submit_notification_failed", error=str(exc))


@celery.task(name="apply.enqueue_for_user")
def enqueue_for_user(user_id: str) -> dict:
    """Queue matched applications for a user, respecting the concurrency cap."""
    return run_async(_enqueue_async(user_id))


async def _enqueue_async(user_id: str) -> dict:
    uid = uuid.UUID(user_id)

    # Count what is ALREADY in flight, or the cap is meaningless: each call would
    # add another MAX_CONCURRENT_PER_USER on top of the running batch.
    in_flight = await JobApplication.find(
        JobApplication.user_id == uid,
        {"status": {"$in": IN_FLIGHT_STATUSES}},
    ).count()
    budget = MAX_CONCURRENT_PER_USER - in_flight
    if budget <= 0:
        return {"queued": 0, "in_flight": in_flight, "detail": "at_concurrency_limit"}

    user = await User.get(uid)
    if user is None or not user.is_active or not user.is_email_verified:
        return {"queued": 0, "detail": "user_not_eligible"}
    # Re-checked here, not only in the sweep: a task queued a moment before the
    # user hit pause is already on the broker and would otherwise still submit
    # an application in their name after they asked us to stop.
    if user.automation_state in {
        AutomationState.PAUSED.value,
        AutomationState.STOPPED.value,
    }:
        return {"queued": 0, "detail": f"automation_{user.automation_state}"}
    if not await billing.can_apply(user.tenant_id):
        return {"queued": 0, "detail": "quota_exhausted"}

    pending = await (
        JobApplication.find(
            JobApplication.user_id == uid,
            JobApplication.status == ApplicationStatus.MATCHED.value,
        )
        .sort(-JobApplication.match_score)
        .limit(budget)
        .to_list()
    )

    profile = await Profile.find_one(Profile.user_id == uid)
    wants_tailoring = bool(profile and profile.resume_strategy == "tailored")

    queued = 0
    for app_row in pending:
        app_row.status = ApplicationStatus.QUEUED.value
        _record_event(app_row, "queued")
        app_row.touch()
        await app_row.save()
        if wants_tailoring and app_row.resume_document_id is None:
            # Tailor first, then submit: chaining keeps the per-job résumé
            # attached instead of leaving tailoring as unreachable code.
            from app.workers.tasks.tailoring import tailor_for_application

            (
                tailor_for_application.si(str(app_row.id))
                | submit_application.si(str(app_row.id))
            ).apply_async()
        else:
            submit_application.delay(str(app_row.id))
        queued += 1

    return {"queued": queued, "in_flight": in_flight}


@celery.task(name="apply.verify_managed_account")
def verify_managed_account(inbound_email_id: str, credential_id: str) -> dict:
    """Follow a site's verification link for an account we created.

    The link was already vetted at ingest (same registrable domain as both the
    sender and the pending credential), and this task re-checks the pairing
    before opening anything. On success the credential goes active and every
    application parked on this site is re-queued — the "that simple" the user
    was promised, without them touching an inbox.
    """
    return run_async(_verify_managed_async(inbound_email_id, credential_id))


async def _verify_managed_async(inbound_email_id: str, credential_id: str) -> dict:
    from app.models.profile import InboundEmail, SiteCredential
    from app.services.apply_email import registrable_domain

    mail = await InboundEmail.get(uuid.UUID(inbound_email_id))
    credential = await SiteCredential.get(uuid.UUID(credential_id))
    if mail is None or credential is None or not mail.verification_url:
        return {"status": "skipped", "detail": "missing_row_or_url"}
    if credential.status != "pending_verification" or not credential.managed:
        return {"status": "skipped", "detail": "credential_not_pending"}
    # Belt and braces on top of ingest-time vetting.
    if registrable_domain(mail.verification_url) != credential.site_domain:
        log.warning("verification_domain_mismatch",
                    link=mail.verification_url[:80], site=credential.site_domain)
        return {"status": "skipped", "detail": "domain_mismatch"}

    try:
        from app.services.ats.base import launch_context

        async with launch_context() as context:
            page = await context.new_page()
            await page.goto(mail.verification_url, wait_until="domcontentloaded",
                            timeout=45_000)
    except ImportError:
        return {"status": "skipped", "detail": "automation_unavailable"}
    except Exception as exc:  # noqa: BLE001 - link expired / site down
        log.warning("verification_visit_failed", error=str(exc)[:200])
        return {"status": "failed", "detail": "verification_visit_failed"}

    # "Active" here means "the address is confirmed as far as we can tell".
    # The real proof is the next sign-in; a failure there parks with
    # check_credential, which is honest and recoverable.
    credential.status = "active"
    credential.touch()
    await credential.save()
    mail.processed = True
    await mail.save()

    # Re-queue everything that was waiting on this account.
    user = await User.get(credential.user_id)
    if user is None or user.automation_state in {
        AutomationState.PAUSED.value,
        AutomationState.STOPPED.value,
    }:
        return {"status": "verified", "requeued": 0}

    requeued = 0
    parked = await JobApplication.find(
        JobApplication.user_id == credential.user_id,
        JobApplication.status == ApplicationStatus.NEEDS_INFO.value,
        JobApplication.needs_action == "awaiting_email_verification",
    ).to_list()
    for row in parked:
        job = await Job.get(row.job_id)
        if job is None:
            continue
        if registrable_domain(job.apply_url) != credential.site_domain:
            continue
        row.status = ApplicationStatus.QUEUED.value
        row.needs_action = None
        _record_event(row, "requeued", "email_verified")
        row.touch()
        await row.save()
        submit_application.delay(str(row.id))
        requeued += 1

    log.info("managed_account_verified", site=credential.site_domain,
             requeued=requeued)
    return {"status": "verified", "requeued": requeued}
