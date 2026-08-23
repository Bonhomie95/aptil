"""Mock interview sessions grounded in the user's CV + target job (spec points 15, 19)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.ai import prompts
from app.api.deps import get_verified_user
from app.core.config import settings
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.models.enums import InterviewStatus
from app.models.interview import InterviewSession
from app.models.job import Job
from app.models.profile import Profile
from app.models.user import User
from app.services import billing

router = APIRouter()
log = get_logger(__name__)

MAX_ANSWER_CHARS = 8000


class CreateInterviewRequest(BaseModel):
    job_id: uuid.UUID | None = None
    # Bounded: each question costs an LLM call, so an unbounded count is a
    # direct route to unbounded spend.
    question_count: int = Field(default=8, ge=1, le=settings.MAX_INTERVIEW_QUESTIONS)


class AnswerRequest(BaseModel):
    question_index: int = Field(ge=0)
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)


class QuestionRead(BaseModel):
    type: str = "general"
    question: str
    what_good_looks_like: str | None = None


class SessionSummary(BaseModel):
    id: uuid.UUID
    status: str
    role_context: str | None = None
    question_count: int = 0
    answered_count: int = 0
    overall_score: float | None = None
    created_at: datetime
    completed_at: datetime | None = None


class SessionDetail(SessionSummary):
    questions: list[QuestionRead] = []
    transcript: list[dict] = []
    feedback: dict = {}


def _profile_dict(p: Profile | None) -> dict:
    if not p:
        return {}
    return {
        "headline": p.headline,
        "summary": p.summary,
        "skills": p.skills,
        "work_history": p.work_history,
        "education": p.education,
        "certifications": p.certifications,
    }


def _normalize_questions(raw: object, limit: int) -> list[dict]:
    """Coerce whatever the model returned into a clean question list."""
    items = raw if isinstance(raw, list) else []
    out: list[dict] = []
    for item in items:
        # The cap is checked at the top of the loop, not after the dict branch:
        # a model that returned bare strings used to bypass it entirely, and
        # `limit` is the entitlement the user actually paid for.
        if len(out) >= limit:
            break
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append({"type": "general", "question": text, "what_good_looks_like": ""})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        if not text:
            continue
        out.append(
            {
                "type": str(item.get("type") or "general")[:60],
                "question": text[:2000],
                "what_good_looks_like": str(item.get("what_good_looks_like") or "")[:2000],
            }
        )
    return out


def _summary(session: InterviewSession) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        status=session.status,
        role_context=session.role_context,
        question_count=len(session.questions),
        answered_count=len({t.get("question_index") for t in session.transcript}),
        overall_score=session.overall_score,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )


def _detail(session: InterviewSession) -> SessionDetail:
    base = _summary(session).model_dump()
    return SessionDetail(
        **base,
        questions=[QuestionRead(**q) for q in session.questions],
        transcript=session.transcript,
        feedback=session.feedback,
    )


async def _owned_session(session_id: uuid.UUID, user: User) -> InterviewSession:
    session = await InterviewSession.find_one(
        InterviewSession.id == session_id,
        InterviewSession.user_id == user.id,
        InterviewSession.tenant_id == user.tenant_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("", response_model=list[SessionSummary])
async def list_interviews(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_verified_user),
):
    """Past and in-progress sessions, newest first, so a refresh isn't fatal."""
    sessions = await InterviewSession.find(
        InterviewSession.user_id == user.id,
        InterviewSession.tenant_id == user.tenant_id,
    ).sort(-InterviewSession.created_at).limit(limit).to_list()
    return [_summary(s) for s in sessions]


@router.post(
    "",
    response_model=SessionDetail,
    status_code=201,
    dependencies=[Depends(RateLimiter(times=10, seconds=3600, scope="user"))],
)
async def create_interview(
    payload: CreateInterviewRequest,
    user: User = Depends(get_verified_user),
):
    # Entitlement gate: mock interviews are a metered, paid feature.
    if not await billing.can_interview(user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="interview_quota_exhausted",
        )

    profile = await Profile.find_one(Profile.user_id == user.id)
    job = None
    if payload.job_id:
        job = await Job.get(payload.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
    job_dict = (
        {"title": job.title, "company": job.company, "description": job.description}
        if job
        else None
    )

    # litellm is synchronous; running it inline would block the event loop for
    # the entire API worker while the model responds.
    try:
        generated = await to_thread.run_sync(
            lambda: prompts.generate_interview_questions(
                _profile_dict(profile), job_dict, count=payload.question_count
            )
        )
    except Exception as exc:  # noqa: BLE001 - surface a usable message
        log.error("interview_generation_failed", user_id=str(user.id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't generate questions right now. Please try again.",
        ) from exc

    questions = _normalize_questions(
        (generated or {}).get("questions"), payload.question_count
    )
    if not questions:
        # Never hand back an empty session: the UI would have nothing to render
        # and no way forward.
        log.error("interview_generation_empty", user_id=str(user.id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't generate questions right now. Please try again.",
        )

    session = InterviewSession(
        user_id=user.id,
        tenant_id=user.tenant_id,
        job_id=payload.job_id,
        status=InterviewStatus.CREATED.value,
        role_context=job.title if job else (profile.headline if profile else None),
        questions=questions,
    )
    await session.insert()
    # Only meter once the session actually exists.
    await billing.increment_interview_usage(user.tenant_id)
    return _detail(session)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_interview(
    session_id: uuid.UUID,
    user: User = Depends(get_verified_user),
):
    return _detail(await _owned_session(session_id, user))


@router.post(
    "/{session_id}/answer",
    dependencies=[Depends(RateLimiter(times=60, seconds=3600, scope="user"))],
)
async def submit_answer(
    session_id: uuid.UUID,
    payload: AnswerRequest,
    user: User = Depends(get_verified_user),
):
    session = await _owned_session(session_id, user)
    if session.status == InterviewStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="This session is already complete")
    # `ge=0` on the schema plus this upper bound: a negative index would
    # otherwise wrap around and score against the wrong question.
    if not 0 <= payload.question_index < len(session.questions):
        raise HTTPException(status_code=422, detail="question_index out of range")

    q = session.questions[payload.question_index]
    try:
        scored = await to_thread.run_sync(
            lambda: prompts.score_answer(
                q.get("question", ""),
                payload.answer,
                q.get("what_good_looks_like", ""),
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.error("interview_scoring_failed", session_id=str(session_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't score that answer right now. Please try again.",
        ) from exc

    scored = _clean_feedback(scored)

    entry = {
        "question_index": payload.question_index,
        "question": q.get("question"),
        "answer": payload.answer,
        "feedback": scored,
        "at": datetime.now(UTC).isoformat(),
    }
    # Re-answering a question replaces the previous attempt instead of stacking
    # duplicate transcript rows.
    transcript = [
        t for t in session.transcript if t.get("question_index") != payload.question_index
    ]
    transcript.append(entry)
    transcript.sort(key=lambda t: t.get("question_index", 0))
    session.transcript = transcript
    if session.status == InterviewStatus.CREATED.value:
        session.status = InterviewStatus.IN_PROGRESS.value
    session.touch()
    await session.save()
    return scored


def _clean_feedback(raw: object) -> dict:
    """Clamp the model's feedback into the shape the UI renders."""
    data = raw if isinstance(raw, dict) else {}
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    score = round(max(0.0, min(10.0, score)), 1)

    def _list(key: str) -> list[str]:
        value = data.get(key)
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        return [str(v).strip()[:500] for v in value if str(v).strip()][:6]

    return {
        "score": score,
        "strengths": _list("strengths"),
        "improvements": _list("improvements"),
    }


@router.post("/{session_id}/complete", response_model=SessionDetail)
async def complete_interview(
    session_id: uuid.UUID,
    user: User = Depends(get_verified_user),
):
    """Close the session and record an overall score from the answers given."""
    session = await _owned_session(session_id, user)
    if session.status == InterviewStatus.COMPLETED.value:
        return _detail(session)

    scores = [
        float(t["feedback"]["score"])
        for t in session.transcript
        if isinstance(t.get("feedback"), dict) and t["feedback"].get("score") is not None
    ]
    overall = round(sum(scores) / len(scores), 1) if scores else None

    strengths: list[str] = []
    improvements: list[str] = []
    for t in session.transcript:
        fb = t.get("feedback") or {}
        strengths.extend(fb.get("strengths") or [])
        improvements.extend(fb.get("improvements") or [])

    session.status = InterviewStatus.COMPLETED.value
    session.overall_score = overall
    session.completed_at = datetime.now(UTC)
    session.feedback = {
        "answered": len(session.transcript),
        "total_questions": len(session.questions),
        "strengths": strengths[:8],
        "improvements": improvements[:8],
    }
    session.touch()
    await session.save()
    return _detail(session)


@router.delete("/{session_id}", status_code=204)
async def delete_interview(
    session_id: uuid.UUID,
    user: User = Depends(get_verified_user),
):
    session = await _owned_session(session_id, user)
    await session.delete()
    return None
