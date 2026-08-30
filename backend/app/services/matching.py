"""Transparent, explainable job-matching heuristic.

No ML: matching is a weighted blend of three signals that a user can read and
understand, so results are defensible (compliance §5 — transparency around
automated decisions):

    1. skill overlap   — profile.skills vs. tokens in the job title+description
    2. title similarity — job title vs. the profile's latest work-history title
    3. location/remote  — the profile's preferences vs. the job's location/remote

``score_job`` returns a 0..1 float (and can return a reasons list for the UI).
``match_jobs_for_user`` ranks the shared Job pool and materializes
JobApplication rows for the top N.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import AliasChoices, BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import ApplicationStatus, JobSource
from app.models.job import Job, JobApplication
from app.models.profile import Profile
from app.services.ats import can_auto_apply
from app.services.geo import location_allowed
from app.services.job_cache import is_unapplicable

log = get_logger(__name__)

# Signal weights (sum to 1.0). Tune here; kept explicit for transparency.
W_SKILLS = 0.5
W_TITLE = 0.3
W_LOCATION = 0.2

# How many of the candidate's skills a posting must mention to earn full skill
# credit. Scoring "fraction of ALL my skills" punishes people for listing more:
# someone with 20 skills whose job needs 4 of them scored 20%, which read as a
# terrible match when it was a good one. The extra skills a job doesn't happen
# to need are not evidence against the candidate.
SKILL_TARGET = 3

# A web-search hit's "description" is a search-engine snippet (Serper/Brave/
# Tavily return ~150-160 chars) — the connector's `desc` parameter is literally
# the provider's `snippet`/`content` field, not the posting body. Below this
# length it is a snippet, not real posting text, so zero skill words appearing
# in it is not evidence the role doesn't need them. Other sources (Greenhouse,
# Remotive, the free boards, ...) return the actual posting text and are never
# this short for a real job, so this only ever softens a WEB_SEARCH job.
THIN_DESCRIPTION_CHARS = 200

# Never load the whole collection into memory; cap what one pass considers.
MAX_JOBS_CONSIDERED = 2000


class ScoredJob(BaseModel):
    """The only fields scoring reads, as a Mongo projection.

    A Job also carries the provider's entire API payload in ``raw``; loading
    2000 of those per run moved tens of megabytes out of the database purely to
    throw them away. Field names match ``Job`` so ``score_job`` is unchanged and
    still works on a real document.
    """

    # validation_alias, not alias — see the note on JobRead in routes/jobs.py:
    # a plain alias would also rename the field on serialisation.
    id: uuid.UUID = Field(validation_alias=AliasChoices("_id", "id"))
    company: str
    title: str
    location: str | None = None
    remote: bool | None = None
    description: str | None = None
    # Needed by the auto-appliable filter in match_jobs_for_user — without it
    # the projection drops ats_type and every job looks un-appliable.
    ats_type: str | None = None
    # Needed by _skill_overlap to recognize a web-search snippet (short by
    # nature) rather than treat it like a thin real posting.
    source: str | None = None

    model_config = {"from_attributes": True}

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_STOPWORDS = {
    "the", "and", "for", "with", "you", "our", "are", "will", "this", "that",
    "a", "an", "to", "of", "in", "on", "at", "we", "is", "as", "or", "be",
}


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1
    }


def _phrase_present(phrase: str, haystack: str) -> bool:
    """Whole-word/phrase containment.

    A plain substring test makes one- and two-character skills ("R", "C", "Go")
    match essentially every posting — "r" appears inside countless words — which
    scored unrelated jobs at 100% skill overlap.
    """
    if not phrase:
        return False
    # \b does not anchor against '+'/'#', so bound on non-word-ish characters
    # for skills like "C++" or "C#".
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _latest_title(profile: Profile) -> str | None:
    """The title from the profile's most recent work_history entry.

    work_history is CV-derived; entries are assumed newest-first (as CV parsing
    lists them). Falls back to headline if no work history.
    """
    for entry in profile.work_history or []:
        if isinstance(entry, dict):
            title = entry.get("title") or entry.get("job_title") or entry.get("position")
            if title:
                return str(title)
    return profile.headline


def target_titles(profile: Profile) -> list[str]:
    """Titles to match against, best signal first.

    A stated target beats CV history every time: someone applying to move from
    support into product engineering is badly served by scoring against the job
    they are leaving. Falls back to the CV only when they have told us nothing.
    """
    stated = [
        t.strip()
        for t in (getattr(profile, "target_titles", None) or [])
        if isinstance(t, str) and t.strip()
    ]
    if stated:
        return stated
    latest = _latest_title(profile)
    return [latest] if latest else []


def _skill_overlap(profile: Profile, job: Job | ScoredJob) -> tuple[float, list[str]]:
    skills = [
        s.strip().lower()
        for s in (profile.skills or [])
        if isinstance(s, str) and s.strip()
    ]
    if not skills:
        return 0.0, []
    haystack = f"{job.title or ''} {job.description or ''}".lower()
    if not haystack.strip():
        return 0.0, []

    matched: list[str] = []
    for skill in skills:
        if _phrase_present(skill, haystack):
            matched.append(skill)
            continue
        # Multi-word skills also count when every significant token appears.
        skill_toks = _tokens(skill)
        if len(skill_toks) > 1 and all(
            _phrase_present(tok, haystack) for tok in skill_toks
        ):
            matched.append(skill)

    # Full credit at SKILL_TARGET matches (or at everything the user listed, if
    # they listed fewer). See the note on SKILL_TARGET.
    target = min(len(skills), SKILL_TARGET)
    overlap = min(1.0, len(matched) / target) if target else 0.0

    # A real positive match is real evidence — keep it. But a ZERO from a web
    # search hit's snippet isn't evidence the role doesn't need these skills,
    # it's just too little text to tell — score that as unknown (neutral), the
    # same rule `_location_score` already applies when it has no usable signal,
    # not as a strike against the job. Scoped to WEB_SEARCH specifically: every
    # other source (Greenhouse, the free boards, ...) returns the real posting
    # body, where a genuine zero-overlap IS evidence the role doesn't fit (see
    # test_short_skills_do_not_match_everything) and must still count as one.
    is_web_search_snippet = (
        getattr(job, "source", None) == JobSource.WEB_SEARCH.value
        and len((job.description or "").strip()) < THIN_DESCRIPTION_CHARS
    )
    if not matched and is_web_search_snippet:
        return 0.5, matched

    return overlap, matched


# Words that describe level rather than the job itself. Matching on these alone
# would make "Senior Marketing Manager" look like "Senior Backend Engineer".
_SENIORITY = {
    "senior", "staff", "principal", "lead", "junior", "mid", "associate",
    "head", "director", "vp", "chief", "i", "ii", "iii", "sr", "jr",
}

# Words that describe the KIND of job but not its DOMAIN. "Engineer" is shared by
# almost every technical role, so crediting it made "Platform Engineer" look 50%
# similar to "Machine Learning Infrastructure Engineer". These never count as a
# role match on their own — only the domain words (platform, cloud, security,
# reliability, data, …) do.
_GENERIC_ROLE = {
    "engineer", "engineering", "developer", "dev", "programmer", "manager",
    "management", "specialist", "analyst", "consultant", "administrator",
    "architect", "coordinator", "officer", "representative", "agent",
    "technician", "professional", "expert", "practitioner", "member",
    "worker", "personnel", "of", "and", "the", "for", "in", "a", "an",
}
_IGNORED_TOKENS = _SENIORITY | _GENERIC_ROLE

# Common role acronyms expanded so a target of "SRE" still matches a posting for
# "Site Reliability Engineer" (and vice versa).
_ROLE_ACRONYMS = {
    "sre": {"site", "reliability"},
    "swe": {"software"},
    "sde": {"software"},
    "ml": {"machine", "learning"},
    "ai": {"artificial", "intelligence"},
    "qa": {"quality", "assurance"},
    "ux": {"user", "experience"},
    "ui": {"user", "interface"},
    "pm": {"product"},
    "devops": {"devops"},
    "sysadmin": {"systems", "administrator"},
}


def _domain_tokens(title: str | None) -> set[str]:
    """Meaningful (domain) tokens of a title: acronyms expanded, generic and
    seniority words removed."""
    toks = _tokens(title)
    out: set[str] = set()
    for t in toks:
        out |= _ROLE_ACRONYMS.get(t, {t})
    return out - _IGNORED_TOKENS


def role_relevant(profile: Profile, job: Job | ScoredJob) -> bool:
    """Whether a posting's title is actually one of the roles the user wants.

    A HARD gate: with target titles set, a job whose title shares no domain word
    with ANY target is dropped, no matter how well its skills or location score.
    This is what stops an SRE seeker's dashboard filling with unrelated senior
    engineering roles.
    """
    targets = target_titles(profile)
    if not targets:
        return True  # nothing stated -> don't gate
    job_dom = _domain_tokens(job.title)
    if not job_dom:
        return True  # title is only generic words; don't over-filter
    job_norm = _normalize(job.title)
    for t in targets:
        t_dom = _domain_tokens(t)
        if t_dom and (t_dom & job_dom):
            return True
        # Whole-phrase containment catches "Cloud Engineer" inside
        # "Cloud Engineer, Data Platform" even when tokenisation differs.
        t_norm = _normalize(t)
        if t_norm and t_norm in job_norm:
            return True
    return False


def _target_domain_tokens(profile: Profile) -> set[str]:
    """Union of domain tokens across every stated/derived target title.

    Feeds the DB-side title prefilter in ``match_jobs_for_user`` — see
    ``_title_regex``.
    """
    out: set[str] = set()
    for t in target_titles(profile):
        out |= _domain_tokens(t)
    return out


def _title_regex(domain_tokens: set[str]) -> str | None:
    """Whole-word alternation of ``domain_tokens``, for a Mongo ``$regex``
    prefilter on ``Job.title``. ``None`` if there is nothing to search for.

    Precision does not matter here — ``role_relevant`` still makes the exact
    accept/reject call in Python afterward. This only decides which jobs are
    worth pulling out of a pool that can run into the tens of thousands, so a
    false-positive match just costs one extra (cheap) scoring pass, while a
    false negative would silently hide a real match — the risk this exists to
    close (see match_jobs_for_user's MAX_JOBS_CONSIDERED note).
    """
    escaped = sorted(re.escape(t) for t in domain_tokens if t)
    if not escaped:
        return None
    return r"(?<![a-z0-9])(" + "|".join(escaped) + r")(?![a-z0-9])"


def _title_similarity(profile: Profile, job: Job | ScoredJob) -> float:
    """Overlap between the user's most recent title and the posting's.

    Uses the overlap coefficient (|A∩B| / min(|A|,|B|)) rather than Jaccard.
    Jaccard punished longer titles for being longer: "Senior Backend Engineer"
    vs "Software Engineer, Backend" scored 0.5 despite being the same job.
    Seniority words are scored separately and at lower weight so they cannot
    carry a match on their own.
    """
    b = _tokens(job.title)
    if not b:
        return 0.0

    # Score against every stated target and keep the best. A user looking for
    # either "SRE" or "Platform Engineer" should match a posting for either,
    # rather than being averaged into matching neither well.
    b_dom = _domain_tokens(job.title)
    best = 0.0
    for candidate in target_titles(profile):
        a_dom = _domain_tokens(candidate)
        if a_dom and b_dom:
            core = len(a_dom & b_dom) / min(len(a_dom), len(b_dom))
        else:
            core = 0.0
        # A shared seniority level is a weak positive, not a match in itself.
        a, b = _tokens(candidate), _tokens(job.title)
        level = 1.0 if (a & _SENIORITY) & (b & _SENIORITY) else 0.0
        best = max(best, 0.85 * core + 0.15 * level)
    return round(min(1.0, best), 4)


def _location_score(profile: Profile, job: Job | ScoredJob) -> float:
    prefs: dict[str, Any] = profile.preferences or {}
    wants_remote = bool(prefs.get("remote"))
    if wants_remote and job.remote:
        return 1.0

    pref_locations = prefs.get("locations") or []
    if isinstance(pref_locations, str):
        pref_locations = [pref_locations]
    job_loc = (job.location or "").lower()
    if job_loc and pref_locations:
        for loc in pref_locations:
            if isinstance(loc, str) and loc.strip() and loc.lower() in job_loc:
                return 1.0
        # Remote roles still suit a location-constrained candidate.
        return 0.5 if job.remote else 0.0
    # No usable preference signal -> neutral (don't penalize).
    return 0.5


def score_job(
    profile: Profile, job: Job | ScoredJob, *, with_reasons: bool = False
) -> float | tuple[float, list[str]]:
    """Score how well ``job`` fits ``profile`` on a 0..1 scale."""
    skills, matched = _skill_overlap(profile, job)
    title = _title_similarity(profile, job)
    location = _location_score(profile, job)

    score = W_SKILLS * skills + W_TITLE * title + W_LOCATION * location
    score = round(min(1.0, max(0.0, score)), 4)

    if not with_reasons:
        return score

    # skills == 0.5 with nothing matched is _skill_overlap's neutral case (a
    # web-search snippet too short to judge), not a real 50% overlap — say so
    # plainly rather than showing a number that looks computed.
    if matched:
        skill_reason = f"Skill overlap {skills:.0%} — matched {', '.join(matched[:6])}"
    elif skills == 0.5:
        skill_reason = "Skill overlap unknown — posting text was too short to check"
    else:
        skill_reason = f"Skill overlap {skills:.0%} — no skills matched"

    reasons = [
        skill_reason,
        f"Title similarity {title:.0%} vs your most recent role",
        f"Location/remote fit {location:.0%}",
    ]
    return score, reasons


def _normalize(text: str | None) -> str:
    """Lower-case, punctuation-free form for comparing names.

    Defined here rather than imported from the discovery worker: services must
    not depend on worker modules.
    """
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# Legal-entity suffixes stripped before comparing company names, so excluding
# "Acme" also excludes "Acme, Inc." / "Acme LLC" / "Acme Corporation".
_COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "llp", "ltd", "limited", "corp",
    "corporation", "co", "company", "gmbh", "plc", "sa", "ag", "nv", "bv",
    "group", "holdings", "holding", "labs", "technologies", "technology",
}


def _company_key(name: str | None) -> str:
    """Company name reduced to a comparison key.

    Lowercased, split on non-alphanumerics, trailing legal-entity suffixes
    dropped, then rejoined. "Acme, Inc." and "ACME" both become "acme".

    Deliberately EXACT after this: excluding "Meta" must not also exclude
    "Metabase", so we compare whole normalised names, never substrings.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t]
    # Drop a leading article so "The Walt Disney Company" and "Walt Disney"
    # collapse together.
    if len(tokens) > 1 and tokens[0] == "the":
        tokens.pop(0)
    while len(tokens) > 1 and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


def _target_country_codes(profile: Profile) -> set[str]:
    """The user's chosen countries as ISO-2 codes (continents expanded).

    Empty when they picked nothing, which disables the location filter.
    """
    from app.services.geo import resolve_countries

    return set(resolve_countries(getattr(profile, "target_countries", None) or []))


def _excluded_company_keys(profile: Profile) -> set[str]:
    return {
        _company_key(c)
        for c in (getattr(profile, "excluded_companies", None) or [])
        if isinstance(c, str) and c.strip()
    }


def _role_key(job: Job | ScoredJob) -> tuple[str, str]:
    """Identity of a *role*, ignoring which office it is posted for.

    Fingerprinting includes location on purpose (the same title in two cities is
    two openings), but showing a user the same role five times because it is
    listed in five offices is noise, not choice.
    """
    raw = job.title or ""
    # Drop a parenthesised/bracketed qualifier — "(Remote)", "(London)", "[EMEA]"
    # — before normalising, since normalising removes the brackets themselves.
    raw = re.split(r"[(\[]", raw)[0]
    return (_normalize(job.company or ""), _normalize(raw))


def diversify(
    scored: list[tuple[float, list[str], Job | ScoredJob]],
    limit: int,
    max_per_company: int,
) -> list[tuple[float, list[str], Job | ScoredJob]]:
    """Best ``limit`` results, capped at ``max_per_company`` per employer, and
    with the same role never listed twice.

    Pure top-N ranking hands the whole dashboard to whichever company has the
    most open postings — a board contributing a third of the pool takes a third
    of every user's matches regardless of fit.

    If the cap leaves the list very short, it is relaxed once (to double the
    cap) rather than abandoned. Beyond that we return fewer results on purpose:
    a shorter, varied list is more useful than a long list from two employers.
    """
    seen_roles: set[tuple[str, str]] = set()
    unique: list[tuple[float, list[str], Job | ScoredJob]] = []
    for entry in scored:  # already sorted best-first
        key = _role_key(entry[2])
        if key in seen_roles:
            continue
        seen_roles.add(key)
        unique.append(entry)

    def pass_with(cap: int) -> list[tuple[float, list[str], Job | ScoredJob]]:
        picked: list[tuple[float, list[str], Job | ScoredJob]] = []
        per_company: dict[str, int] = {}
        for entry in unique:
            company = _normalize(entry[2].company or "")
            if per_company.get(company, 0) >= cap:
                continue
            picked.append(entry)
            per_company[company] = per_company.get(company, 0) + 1
            if len(picked) >= limit:
                break
        return picked

    picked = pass_with(max_per_company)
    # Only relax when the strict cap produced a nearly-empty list.
    if len(picked) < max(3, limit // 4):
        picked = pass_with(max_per_company * 2)
    return picked


async def match_jobs_for_user(
    user_id: uuid.UUID,
    limit: int = 20,
    min_score: float | None = None,
) -> int:
    """Rank the shared Job pool for a user and create matched applications.

    Creates JobApplication documents (status "matched", ``match_score`` set) for
    the best-fitting jobs the user does not already have an application for.

    Two quality guards apply:
      * anything below ``min_score`` (default ``settings.MIN_MATCH_SCORE``) is
        dropped rather than padding the dashboard with weak matches;
      * no employer may take more than ``MAX_MATCHES_PER_COMPANY`` of the run.

    Returns the number of applications created.
    """
    profile = await Profile.find_one(Profile.user_id == user_id)
    if profile is None:
        log.warning("matching_no_profile", user_id=str(user_id))
        return 0

    # Only the job ids are needed for the "already applied" filter — project to
    # that single field so a long application history stays cheap to read.
    existing_rows = (
        await JobApplication.find(JobApplication.user_id == user_id)
        .aggregate([{"$project": {"_id": 0, "job_id": 1}}])
        .to_list()
    )
    existing_job_ids = {row["job_id"] for row in existing_rows if row.get("job_id")}

    # Bounded scan instead of loading the entire collection, and projected to
    # the fields scoring actually reads (see ScoredJob). Restricted to jobs
    # Aptil can actually apply to, so the scan budget surfaces appliable
    # matches instead of being spent on company-hosted pages we would drop.
    from app.services.ats import auto_appliable_ats_types

    base_criteria: dict = {"ats_type": {"$in": auto_appliable_ats_types()}}

    # Relevance before recency. A plain "newest N" scan starves any user whose
    # target role isn't well-represented in whatever was JUST re-fetched: the
    # pool runs into the tens of thousands, "newest 2000" is a thin recency
    # slice of it, and a niche/specific title can have nearly all of its real
    # candidates sitting outside that slice — found below newest-2000 by
    # created_at even though they'd score well. Search by the user's own
    # target-title words FIRST, so a good candidate is found regardless of
    # when it happened to be (re)discovered, then only fall back to (and top
    # up with) the broad newest-first scan — which is exactly the old
    # behavior — for users with no clear target, or when the targeted search
    # alone comes back too thin to be worth ranking.
    jobs: list[ScoredJob] = []
    seen_ids: set[uuid.UUID] = set()

    pattern = _title_regex(_target_domain_tokens(profile))
    if pattern:
        targeted = (
            await Job.find({**base_criteria, "title": {"$regex": pattern, "$options": "i"}})
            .sort(-Job.created_at)
            .limit(MAX_JOBS_CONSIDERED)
            .project(ScoredJob)
            .to_list()
        )
        jobs.extend(targeted)
        seen_ids.update(j.id for j in targeted)

    # Thin-result threshold, not "only when empty": a handful of targeted hits
    # isn't enough to rank well, and a real fit whose title shares no literal
    # word with the target (a synonym the acronym table doesn't cover) is only
    # ever reachable through this broad pass.
    if len(jobs) < max(limit * 3, 200):
        remaining = MAX_JOBS_CONSIDERED - len(jobs)
        if remaining > 0:
            broad = (
                await Job.find(base_criteria)
                .sort(-Job.created_at)
                .limit(remaining)
                .project(ScoredJob)
                .to_list()
            )
            jobs.extend(j for j in broad if j.id not in seen_ids)

    excluded = _excluded_company_keys(profile)
    allowed_countries = _target_country_codes(profile)

    # Roles the user already has an application for, so the SAME role in a
    # different city (a distinct job_id, so existing_job_ids misses it) is not
    # matched a second time. This is the cross-run half of dedupe; diversify()
    # handles within-run.
    existing_role_keys: set[tuple[str, str]] = set()
    if existing_job_ids:
        applied_jobs = (
            await Job.find({"_id": {"$in": list(existing_job_ids)}})
            .project(ScoredJob)
            .to_list()
        )
        existing_role_keys = {_role_key(j) for j in applied_jobs}

    seen_role_keys: set[tuple[str, str]] = set(existing_role_keys)
    scored: list[tuple[float, list[str], Job | ScoredJob]] = []
    for job in jobs:
        if job.id in existing_job_ids:
            continue
        # A company the user has excluded must never become an application, no
        # matter how well it scores — this is a hard filter, not a penalty.
        if excluded and _company_key(job.company) in excluded:
            continue
        # Location gate: chose USA -> drop clearly non-US postings.
        if not location_allowed(job.location, allowed_countries):
            continue
        # Only surface jobs Aptil can actually apply to end to end. Company-
        # hosted pages and park-only ATSes (Workday) are skipped entirely — the
        # user never sees a job that would just sit in a "you finish it" pile.
        if not can_auto_apply(getattr(job, "ats_type", None)):
            continue
        # Recently attempted and could not complete (CAPTCHA, login wall, …).
        # Skip so we don't recreate an application that would just be discarded
        # again. The marker expires, so it is retried later.
        if is_unapplicable(str(user_id), str(job.id)):
            continue
        # Role gate: the title must actually be one of the roles the user wants.
        # Without this an SRE seeker's list fills with unrelated senior
        # engineering roles that merely share the word "Engineer".
        if not role_relevant(profile, job):
            continue
        # Cross-listing dedupe: same role+company already chosen (this run or a
        # previous one) is not offered again in another city.
        rk = _role_key(job)
        if rk in seen_role_keys:
            continue
        seen_role_keys.add(rk)
        value, reasons = score_job(profile, job, with_reasons=True)  # type: ignore[misc]
        scored.append((value, reasons, job))

    scored.sort(key=lambda triple: triple[0], reverse=True)

    threshold = settings.MIN_MATCH_SCORE if min_score is None else min_score
    above = [t for t in scored if t[0] >= threshold]
    if not above and scored:
        log.info(
            "matching_all_below_threshold",
            user_id=str(user_id),
            best=round(scored[0][0], 3),
            threshold=threshold,
        )

    selected = diversify(above, max(0, limit), settings.MAX_MATCHES_PER_COMPANY)

    created = 0
    for score, reasons, job in selected:
        application = JobApplication(
            tenant_id=profile.tenant_id,
            user_id=user_id,
            job_id=job.id,
            status=ApplicationStatus.MATCHED.value,
            match_score=score,
            match_reasons=reasons,
        )
        try:
            await application.insert()
        except DuplicateKeyError:
            # Raced another matching pass for the same user/job; not an error.
            continue
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the run
            log.warning(
                "matching_insert_failed",
                user_id=str(user_id),
                job_id=str(job.id),
                error=str(exc),
            )
            continue
        created += 1

    log.info(
        "matching_done",
        user_id=str(user_id),
        candidates=len(scored),
        above_threshold=len(above),
        threshold=threshold,
        companies=len({j.company for _s, _r, j in selected}),
        created=created,
    )
    return created
