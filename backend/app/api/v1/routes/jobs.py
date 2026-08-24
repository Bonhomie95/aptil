"""Jobs and applications — powers the dashboard stats (spec point 14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AliasChoices, BaseModel, Field

from app.api.deps import get_current_user, get_verified_user
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.models.enums import ApplicationStatus, AutomationState
from app.models.job import Job, JobApplication
from app.models.user import User
from app.services import billing

router = APIRouter()

# Statuses shown on the dashboard by default: the pipeline toward a real
# application plus genuine employer outcomes. Parked (needs_info) and failed are
# excluded — a job Aptil could not apply to is never surfaced.
_VISIBLE_STATUSES = [
    ApplicationStatus.MATCHED.value,
    ApplicationStatus.QUEUED.value,
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.CONFIRMED.value,
    ApplicationStatus.INTERVIEW.value,
    ApplicationStatus.OFFER.value,
    ApplicationStatus.REJECTED.value,
]
log = get_logger(__name__)

# Statuses a user is allowed to set by hand (tracking their own pipeline).
# Deliberately NOT including SUBMITTED: "we applied" is a claim only the engine
# makes, and only when the employer's page confirms it (compliance section 2a).
# A user marking a row submitted by hand would manufacture evidence of an
# application that never happened. The dashboard therefore renders the current
# status as a disabled option rather than an offer — see the picker in
# frontend/src/app/dashboard/page.tsx.
USER_SETTABLE_STATUSES = {
    ApplicationStatus.INTERVIEW.value,
    ApplicationStatus.OFFER.value,
    ApplicationStatus.REJECTED.value,
    ApplicationStatus.CONFIRMED.value,
}


class JobRead(BaseModel):
    # Doubles as a Mongo projection: the list endpoints read only these fields
    # instead of pulling whole Job documents, each of which carries the
    # provider's full API payload in `raw`.
    #
    # validation_alias, NOT alias: a plain `alias` also renames the field on the
    # way OUT (FastAPI serialises by_alias), so the JSON key became "_id" and
    # every `job.id` in the client was undefined. AliasChoices accepts the
    # projection's "_id" and a document's "id" alike, and output stays "id".
    id: uuid.UUID = Field(validation_alias=AliasChoices("_id", "id"))
    company: str
    title: str
    location: str | None = None
    remote: bool | None = None
    source: str
    apply_url: str
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    posted_at: datetime | None = None
    model_config = {"from_attributes": True}


class ApplicationRead(BaseModel):
    id: uuid.UUID
    status: str
    match_score: float | None
    match_reasons: list[str] = []
    error_message: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    # What the apply engine filled in, so "needs attention" is explainable.
    submitted_fields: dict = {}
    needs_action: str | None = None
    credential_id: uuid.UUID | None = None
    # Null when the underlying posting was purged; the row still counts in stats.
    job: JobRead | None = None
    model_config = {"from_attributes": True}


class StatusUpdate(BaseModel):
    status: str


class QueueResponse(BaseModel):
    queued: int
    detail: str | None = None
    task_id: str | None = None


class MatchStatus(BaseModel):
    running: bool
    task_id: str | None = None
    started_at: str | None = None


# Redis key holding the in-flight matching task for a user, so a run can be
# shown as running and cancelled. Expires by itself if a worker dies mid-run.
_MATCH_KEY = "match:active:{user_id}"
_MATCH_TTL_SECONDS = 900


async def _match_state(user_id: uuid.UUID) -> dict | None:
    import json

    from app.core.ratelimit import _get_redis

    try:
        raw = await _get_redis().get(_MATCH_KEY.format(user_id=user_id))
    except Exception as exc:  # noqa: BLE001 - status is best-effort
        log.warning("match_state_unavailable", error=str(exc)[:120])
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def _set_match_state(user_id: uuid.UUID, task_id: str) -> None:
    import json

    from app.core.ratelimit import _get_redis

    try:
        await _get_redis().set(
            _MATCH_KEY.format(user_id=user_id),
            json.dumps({"task_id": task_id, "started_at": _now_iso()}),
            ex=_MATCH_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("match_state_write_failed", error=str(exc)[:120])


async def _clear_match_state(user_id: uuid.UUID) -> None:
    from app.core.ratelimit import _get_redis

    try:
        await _get_redis().delete(_MATCH_KEY.format(user_id=user_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("match_state_clear_failed", error=str(exc)[:120])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/available", response_model=list[JobRead])
async def available_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    search: str | None = Query(default=None, max_length=100),
    remote: bool | None = None,
    user: User = Depends(get_current_user),
):
    """Jobs surfaced by discovery, filtered to the user's chosen countries.

    The Job pool is shared across users (spec point 9), but browsing it must
    still respect THIS user's location and excluded-company choices — otherwise
    someone who picked "USA" sees other countries here even though their
    dashboard does not.
    """
    criteria: dict = {}
    if search:
        # Escaped so user input is treated as text, never as a regex.
        import re as _re

        pattern = _re.escape(search.strip())
        criteria["$or"] = [
            {"title": {"$regex": pattern, "$options": "i"}},
            {"company": {"$regex": pattern, "$options": "i"}},
        ]
    if remote is not None:
        criteria["remote"] = remote

    from app.services.geo import location_allowed
    from app.services.matching import _company_key

    countries, excluded = await _user_filters(user)

    # Location/company filters are on unstructured text, so they run in Python.
    # Over-fetch to refill what the filter removes, then trim to `limit`.
    overscan = limit * 4 if (countries or excluded) else limit
    query = Job.find(criteria) if criteria else Job.find()
    rows = await (
        query.sort(-Job.created_at)
        .skip(offset)
        .limit(overscan)
        .project(JobRead)
        .to_list()
    )
    kept = [
        j for j in rows
        if location_allowed(getattr(j, "location", None), countries)
        and not (excluded and _company_key(getattr(j, "company", None)) in excluded)
    ]
    return kept[:limit]


async def _user_filters(user: User):
    """The user's current location + company preferences, for filtering lists.

    Returns (allowed_country_codes, excluded_company_keys). Either may be empty,
    which disables that filter.
    """
    from app.models.profile import Profile
    from app.services.geo import resolve_countries
    from app.services.matching import _company_key

    profile = await Profile.find_one(Profile.user_id == user.id)
    if profile is None:
        return set(), set()
    countries = set(resolve_countries(profile.target_countries or []))
    excluded = {
        _company_key(c)
        for c in (profile.excluded_companies or [])
        if isinstance(c, str) and c.strip()
    }
    return countries, excluded


@router.get("/applications", response_model=list[ApplicationRead])
async def my_applications(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    include_all: bool = Query(
        default=False,
        description="Include parked/failed applications. Off by default so the "
        "dashboard shows only jobs Aptil could apply to — pending, applied, or "
        "further along — and never a pile of things it couldn't complete.",
    ),
    user: User = Depends(get_current_user),
):
    criteria: dict = {"user_id": user.id, "tenant_id": user.tenant_id}
    if status_filter:
        criteria["status"] = status_filter
    elif not include_all:
        # Only the pipeline toward a real application: matched (pending),
        # queued (in flight), submitted/confirmed, and the human outcomes
        # (interview/offer/rejected). Everything Aptil could NOT complete —
        # needs_info (parked, captcha, credential, company-site) and failed —
        # is hidden entirely. The user only ever sees jobs it applied to or is
        # applying to.
        criteria["status"] = {"$in": _VISIBLE_STATUSES}

    # Best match first: the primary action on this list is "Apply", so the roles
    # the engine rates highest should be the ones the user sees without
    # scrolling. Recency breaks ties.
    apps = await JobApplication.find(criteria).sort(
        [("match_score", -1), ("created_at", -1)]
    ).skip(offset).limit(limit).to_list()

    # No cross-document joins in Mongo — fetch the referenced jobs in one pass.
    job_ids = list({app.job_id for app in apps})
    jobs = (
        await Job.find({"_id": {"$in": job_ids}}).project(JobRead).to_list()
        if job_ids
        else []
    )
    jobs_by_id = {job.id: job for job in jobs}

    # Hide rows that no longer fit the user's current location/company choices —
    # but ONLY while they are still just "matched" (not yet acted on). This makes
    # stale cross-country matches (e.g. from before the user picked USA)
    # disappear on reload without a re-match, while never hiding an application
    # the user has already engaged with.
    from app.services.geo import location_allowed
    from app.services.matching import _company_key, _role_key

    countries, excluded = await _user_filters(user)

    def _keep(app_row) -> bool:
        if app_row.status != ApplicationStatus.MATCHED.value:
            return True
        job = jobs_by_id.get(app_row.job_id)
        if job is None:
            return True
        if excluded and _company_key(job.company) in excluded:
            return False
        return location_allowed(getattr(job, "location", None), countries)

    # Collapse cross-listing duplicates in the display: the same role at the same
    # company (a different city, so a distinct row) shows once. Applied/engaged
    # rows are never hidden — dedupe only among still-"matched" rows, keeping the
    # first (already sorted best-score-first).
    seen_roles: set[tuple[str, str]] = set()

    def _not_duplicate(app_row) -> bool:
        if app_row.status != ApplicationStatus.MATCHED.value:
            return True
        job = jobs_by_id.get(app_row.job_id)
        if job is None:
            return True
        key = _role_key(job)
        if key in seen_roles:
            return False
        seen_roles.add(key)
        return True

    # A purged Job must not make the row vanish: the dashboard list would then
    # disagree with /stats, which counts every application.
    return [
        ApplicationRead(
            id=app.id,
            status=app.status,
            match_score=app.match_score,
            match_reasons=app.match_reasons,
            error_message=app.error_message,
            submitted_at=app.submitted_at,
            created_at=app.created_at,
            submitted_fields=app.submitted_fields,
            needs_action=app.needs_action,
            credential_id=app.credential_id,
            job=jobs_by_id.get(app.job_id),
        )
        for app in apps
        if _keep(app) and _not_duplicate(app)
    ]


@router.get("/stats")
async def dashboard_stats(user: User = Depends(get_current_user)):
    """Counts per application status for the dashboard."""
    pipeline = [
        {"$match": {"user_id": user.id, "tenant_id": user.tenant_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    rows = await JobApplication.aggregate(pipeline).to_list()
    by_status = {row["_id"]: row["count"] for row in rows if row.get("_id")}
    sub = await billing.get_active_subscription(user.tenant_id)

    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "applications_used": sub.applications_used if sub else 0,
    }


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
async def update_application_status(
    application_id: uuid.UUID,
    payload: StatusUpdate,
    user: User = Depends(get_current_user),
):
    """Let the user record real-world progress (interview, offer, rejection)."""
    if payload.status not in USER_SETTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of {sorted(USER_SETTABLE_STATUSES)}",
        )
    app_row = await JobApplication.find_one(
        JobApplication.id == application_id,
        JobApplication.user_id == user.id,
        JobApplication.tenant_id == user.tenant_id,
    )
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application not found")

    app_row.status = payload.status
    app_row.events = [
        *app_row.events,
        {
            "at": datetime.now(UTC).isoformat(),
            "kind": "status_set_by_user",
            "detail": payload.status,
        },
    ]
    app_row.touch()
    await app_row.save()

    job = await Job.get(app_row.job_id)
    return ApplicationRead(
        id=app_row.id,
        status=app_row.status,
        match_score=app_row.match_score,
        match_reasons=app_row.match_reasons,
        error_message=app_row.error_message,
        submitted_at=app_row.submitted_at,
        created_at=app_row.created_at,
        submitted_fields=app_row.submitted_fields,
        needs_action=app_row.needs_action,
        credential_id=app_row.credential_id,
        job=JobRead.model_validate(job) if job else None,
    )


@router.post(
    "/match",
    response_model=QueueResponse,
    dependencies=[Depends(RateLimiter(times=6, seconds=3600, scope="user"))],
)
async def request_matching(user: User = Depends(get_verified_user)):
    """Rank the shared pool for this user now, instead of waiting for the
    scheduled sweep."""
    # source_for_user, not bare match_for_user: ranking can only reorder what
    # the pool already holds. Fetching by the user's own target titles first is
    # what makes the button return THEIR jobs instead of the pool's bias.
    from app.workers.tasks.sourcing import source_for_user

    # Don't stack runs: a second click while one is going duplicates the work
    # and leaves the stop button pointing at the wrong task.
    existing = await _match_state(user.id)
    if existing:
        return QueueResponse(
            queued=0,
            task_id=existing.get("task_id"),
            detail="A search is already running.",
        )

    try:
        async_result = source_for_user.delay(str(user.id))
    except Exception as exc:  # noqa: BLE001 - broker down
        log.error("match_enqueue_failed", user_id=str(user.id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Matching is temporarily unavailable. Please try again shortly.",
        ) from exc

    await _set_match_state(user.id, async_result.id)
    return QueueResponse(queued=1, task_id=async_result.id, detail="Searching for matches…")


@router.get("/match/status", response_model=MatchStatus)
async def matching_status(user: User = Depends(get_verified_user)):
    """Whether a search is currently running for this user."""
    state = await _match_state(user.id)
    if not state:
        return MatchStatus(running=False)
    try:
        from celery.result import AsyncResult

        from app.workers.celery_app import celery

        # Trust the broker over our marker: a finished task should stop the
        # spinner even if the key has not expired yet.
        if AsyncResult(state["task_id"], app=celery).ready():
            await _clear_match_state(user.id)
            return MatchStatus(running=False)
    except Exception as exc:  # noqa: BLE001 - fall back to the marker
        log.warning("match_status_probe_failed", error=str(exc)[:120])
    return MatchStatus(
        running=True, task_id=state.get("task_id"), started_at=state.get("started_at")
    )


@router.post("/match/cancel", response_model=QueueResponse)
async def cancel_matching(user: User = Depends(get_verified_user)):
    """Stop an in-flight search.

    Revokes the queued task and terminates it if a worker already picked it up,
    so a long sweep is actually called off rather than merely hidden.
    """
    state = await _match_state(user.id)
    if not state:
        return QueueResponse(queued=0, detail="No search is running.")

    task_id = state.get("task_id")
    try:
        from app.workers.celery_app import celery

        celery.control.revoke(task_id, terminate=True, signal="SIGTERM")
    except Exception as exc:  # noqa: BLE001 - clearing the marker still helps
        log.warning("match_cancel_failed", task_id=task_id, error=str(exc)[:120])

    await _clear_match_state(user.id)
    log.info("match_cancelled", user_id=str(user.id), task_id=task_id)
    return QueueResponse(queued=0, task_id=task_id, detail="Search stopped.")


@router.post(
    "/applications/{application_id}/apply",
    response_model=QueueResponse,
    dependencies=[Depends(RateLimiter(times=30, seconds=3600, scope="user"))],
)
async def apply_now(
    application_id: uuid.UUID,
    user: User = Depends(get_verified_user),
):
    """Explicit, per-application consent to submit (compliance §1)."""
    from app.workers.tasks.apply import submit_application

    app_row = await JobApplication.find_one(
        JobApplication.id == application_id,
        JobApplication.user_id == user.id,
        JobApplication.tenant_id == user.tenant_id,
    )
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if app_row.status in (
        ApplicationStatus.QUEUED.value,
        ApplicationStatus.SUBMITTED.value,
        ApplicationStatus.CONFIRMED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application is already queued or submitted",
        )
    if not await billing.can_apply(user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="application_quota_exhausted",
        )

    app_row.status = ApplicationStatus.QUEUED.value
    app_row.touch()
    await app_row.save()
    try:
        submit_application.delay(str(app_row.id))
    except Exception as exc:  # noqa: BLE001
        app_row.status = ApplicationStatus.MATCHED.value
        await app_row.save()
        log.error("apply_enqueue_failed", application_id=str(app_row.id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The apply engine is temporarily unavailable.",
        ) from exc
    return QueueResponse(queued=1, detail="Queued for submission.")


class ApplyBatchRequest(BaseModel):
    # How many of the top matched jobs to submit now. Bounded so one click can
    # never queue an unbounded batch.
    count: int = Field(default=5, ge=1, le=25)


@router.post(
    "/applications/apply-batch",
    response_model=QueueResponse,
    dependencies=[Depends(RateLimiter(times=20, seconds=3600, scope="user"))],
)
async def apply_batch(
    payload: ApplyBatchRequest,
    user: User = Depends(get_verified_user),
):
    """Submit the top-N matched applications in one action (review-then-apply).

    Picks the highest-scoring rows still in ``matched`` and queues them, best
    first, stopping at the plan quota. Explicit per-batch consent (compliance
    §1): nothing is submitted the user did not ask for.
    """
    from app.workers.tasks.apply import submit_application

    rows = (
        await JobApplication.find(
            JobApplication.user_id == user.id,
            JobApplication.tenant_id == user.tenant_id,
            JobApplication.status == ApplicationStatus.MATCHED.value,
        )
        .sort([("match_score", -1), ("created_at", -1)])
        .limit(payload.count)
        .to_list()
    )
    if not rows:
        return QueueResponse(queued=0, detail="No matched jobs to apply to yet.")

    queued = 0
    for app_row in rows:
        # Re-check the quota before EACH submit, so a batch stops exactly at the
        # plan limit instead of overshooting.
        if not await billing.can_apply(user.tenant_id):
            break
        app_row.status = ApplicationStatus.QUEUED.value
        app_row.touch()
        await app_row.save()
        try:
            submit_application.delay(str(app_row.id))
            queued += 1
        except Exception as exc:  # noqa: BLE001 - broker down mid-batch
            app_row.status = ApplicationStatus.MATCHED.value
            await app_row.save()
            log.error("apply_batch_enqueue_failed",
                      application_id=str(app_row.id), error=str(exc))
            break

    detail = (
        f"Queued {queued} application{'s' if queued != 1 else ''} for submission."
        if queued
        else "Couldn't queue any — your plan's application limit may be reached."
    )
    return QueueResponse(queued=queued, detail=detail)


class AutoApplyRequest(BaseModel):
    enabled: bool


@router.post("/auto-apply")
async def set_auto_apply(
    payload: AutoApplyRequest,
    user: User = Depends(get_current_user),
):
    """Toggle background auto-apply. Off = discovery still runs, but the user
    applies in batches themselves."""
    user.auto_apply = payload.enabled
    user.touch()
    await user.save()
    return {"enabled": user.auto_apply}


# --- Automation control ---------------------------------------------------
#
# The engine applies for jobs in the user's name. That makes an off switch a
# requirement, not a feature: someone who accepts an offer, or goes on holiday,
# must be able to stop applications going out without deleting their account.


class AutomationStatus(BaseModel):
    state: str
    changed_at: datetime | None = None
    #: Applications queued but not yet submitted. Shown on pause so the user
    #: knows what is still in flight, and cancelled outright on stop.
    queued: int = 0


class AutomationRequest(BaseModel):
    state: str

    @classmethod
    def _states(cls) -> set[str]:
        return {s.value for s in AutomationState}


async def _queued_count(user_id: uuid.UUID) -> int:
    return await JobApplication.find(
        JobApplication.user_id == user_id,
        JobApplication.status == ApplicationStatus.QUEUED.value,
    ).count()


@router.get("/automation", response_model=AutomationStatus)
async def get_automation(user: User = Depends(get_current_user)):
    return AutomationStatus(
        state=user.automation_state,
        changed_at=user.automation_changed_at,
        queued=await _queued_count(user.id),
    )


@router.post(
    "/automation",
    response_model=AutomationStatus,
    dependencies=[Depends(RateLimiter(times=30, seconds=3600, scope="user"))],
)
async def set_automation(
    payload: AutomationRequest,
    user: User = Depends(get_verified_user),
):
    """Start, pause or stop the search.

    - **running**: source, match and apply on schedule.
    - **paused**: queue nothing new. Anything already queued still goes out —
      it was authorised before the pause, and silently dropping it would leave
      the dashboard showing applications that never happened.
    - **stopped**: as paused, and additionally cancel everything queued but not
      yet submitted, so nothing goes out after the user said stop.
    """
    if payload.state not in AutomationRequest._states():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"state must be one of: {', '.join(sorted(AutomationRequest._states()))}",
        )

    cancelled = 0
    if payload.state == AutomationState.STOPPED.value:
        # Back to `matched`, not `failed`: these are perfectly good matches the
        # user may want to apply to later, and marking them failed would poison
        # the dashboard's success rate with the user's own decision.
        queued = await JobApplication.find(
            JobApplication.user_id == user.id,
            JobApplication.status == ApplicationStatus.QUEUED.value,
        ).to_list()
        for row in queued:
            row.status = ApplicationStatus.MATCHED.value
            row.touch()
            await row.save()
            cancelled += 1

    user.automation_state = payload.state
    user.automation_changed_at = datetime.now(UTC)
    user.touch()
    await user.save()
    log.info(
        "automation_state_changed",
        user_id=str(user.id),
        state=payload.state,
        cancelled=cancelled,
    )
    return AutomationStatus(
        state=user.automation_state,
        changed_at=user.automation_changed_at,
        queued=await _queued_count(user.id),
    )


@router.get("/search-locations")
async def search_locations(user: User = Depends(get_current_user)):
    """Countries and continents the job search supports, for the picker UI.

    Driven by the curated search-country list, so the UI only offers
    locations the search actually targets.
    """
    from app.services.geo import CONTINENTS, SEARCH_COUNTRIES

    continent_labels = {
        "north_america": "North America",
        "south_america": "South America",
        "europe": "Europe",
        "asia": "Asia",
        "oceania": "Oceania",
        "africa": "Africa",
    }
    return {
        "countries": [
            {"code": code, "name": name}
            for code, name in sorted(SEARCH_COUNTRIES.items(), key=lambda kv: kv[1])
        ],
        "continents": [
            {"code": code, "name": continent_labels.get(code, code),
             "countries": members}
            for code, members in CONTINENTS.items()
        ],
    }
