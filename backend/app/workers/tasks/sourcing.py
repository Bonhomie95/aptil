"""Sourcing tasks: run a connector to ingest jobs, and match jobs for a user.

- ``run_source`` resolves a connector from the registry, fetches normalized
  postings, and persists them deduped via ``discovery.upsert_job`` (reusing the
  same fingerprint dedupe as the discovery pipeline).
- ``match_for_user`` ranks the shared Job pool and creates matched applications.

Connectors are synchronous (plain HTTP); persistence and matching are async
(Beanie) and bridged from the sync Celery task with ``app.workers.db.run_async``.
"""

from __future__ import annotations

import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.services.connectors import get_connector
from app.services.matching import match_jobs_for_user
from app.workers.celery_app import celery
from app.workers.db import run_async
from app.workers.tasks.discovery import upsert_job

log = get_logger(__name__)


@celery.task(name="sourcing.run_source")
def run_source(source_name: str, query: dict) -> dict:
    """Fetch postings from ``source_name`` for ``query`` and persist deduped jobs."""
    connector = get_connector(source_name)
    if connector is None:
        log.warning("sourcing_unknown_source", source=source_name)
        return {"source": source_name, "received": 0, "new": 0, "error": "unknown_source"}

    # Connectors are synchronous HTTP clients — fetch outside the async persist loop.
    postings = connector.fetch(query or {})

    # Cap what one board contributes per run. Some company boards carry many
    # hundreds of openings; without a cap they dominate the shared pool, and a
    # skewed pool means skewed matches for every user.
    cap = settings.MAX_POSTINGS_PER_SOURCE
    if cap > 0 and len(postings) > cap:
        log.info("sourcing_truncated", source=source_name,
                 fetched=len(postings), kept=cap)
        postings = postings[:cap]

    inserted = run_async(_persist_async(postings))

    log.info(
        "sourcing_run_source_done",
        source=source_name,
        received=len(postings),
        new=inserted,
    )
    return {"source": source_name, "received": len(postings), "new": inserted}


async def _persist_async(postings: list[dict]) -> int:
    inserted = 0
    for posting in postings:
        _job, created = await upsert_job(posting)
        if created:
            inserted += 1
    return inserted


def _queries_for_profile(profile) -> list[dict]:
    """Aggregator queries describing what THIS user wants.

    Stated targets first; when they have stated nothing, their most recent job
    title — the point is that the query set is always derived from the person's
    own CV, never from a fixed board list someone chose for everyone.
    """
    from app.services.connectors.adzuna import resolve_countries
    from app.services.matching import target_titles

    titles = target_titles(profile)[:4]
    if not titles:
        return []

    # Where to search: the user's explicit target countries (codes/continents),
    # else their home country, else the deployment default. This is the control
    # that lets someone apply across a whole continent or restrict to one place.
    countries = resolve_countries(getattr(profile, "target_countries", None) or [])
    if not countries:
        prefs = profile.preferences or {}
        home = str(
            prefs.get("country") or profile.country or settings.DEFAULT_JOB_COUNTRY
        ).strip().lower()[:2]
        countries = [home] if home.isalpha() else [settings.DEFAULT_JOB_COUNTRY]

    # A city filter only makes sense for a single-country search — "Boston" is
    # meaningless across ten countries, and would drop everything.
    where = (profile.city or "").strip() if len(countries) == 1 else ""

    from app.services.connectors.adzuna import ADZUNA_COUNTRIES

    out = []
    for country in countries:
        # `where` is a HUMAN location for web search ("Boston" or the country
        # name); `country` is the ISO code Adzuna needs. When the user gave a
        # city (single-country case) we prefer it; otherwise fall back to the
        # country's display name so web search is still geo-targeted.
        location = where or ADZUNA_COUNTRIES.get(country, "")
        for title in titles:
            q: dict = {"what": title, "country": country, "results_per_page": 50}
            if location:
                q["where"] = location
            out.append(q)
    # Bound the fan-out: several titles across a whole continent is many API
    # calls per user per sweep. The cap protects the search-API quota; the loop
    # order prioritises countries over extra titles.
    return out[: settings.MAX_DEMAND_QUERIES]


@celery.task(name="sourcing.source_for_user")
def source_for_user(user_id: str) -> dict:
    """Fetch jobs matching this user's own CV/targets, then rank them.

    This is what makes "Find new matches" personal: the shared pool only holds
    what the configured boards carry, so a nurse or a paralegal pressing the
    button against a tech-heavy pool got generic results no matter how good the
    ranking was. Sourcing BY the user's stated titles fixes the pool, not just
    the sort order.
    """
    uid = uuid.UUID(user_id)
    profile = run_async(_profile_for(uid))
    if profile is None:
        return {"user_id": user_id, "fetched": 0, "matched": 0}

    from app.services.matching import _company_key

    excluded = {
        _company_key(c)
        for c in (profile.excluded_companies or [])
        if isinstance(c, str) and c.strip()
    }

    # Which discovery sources are live. Web search is the primary, web-wide
    # path — it finds postings anywhere, not on a fixed board list. Adzuna is
    # optional and off by default now; both feed the same pool if enabled.
    # Query-based sources take the user's role/location per call.
    query_sources: list[str] = []
    # Web search is ready when it's enabled AND either its provider is keyless
    # (SearXNG, self-hosted) or an API key is set. The old gate required a key
    # unconditionally, which silently skipped a keyless SearXNG setup.
    from app.services.connectors.websearch import WebSearchConnector

    _provider = settings.WEB_SEARCH_PROVIDER.strip().lower()
    _web_search_ready = settings.SOURCING_WEB_SEARCH and (
        not WebSearchConnector._NEEDS_KEY.get(_provider, True)
        or bool(settings.WEB_SEARCH_API_KEY.strip())
    )
    if _web_search_ready:
        query_sources.append("web_search")
    if settings.SOURCING_USE_ADZUNA:
        query_sources.append("adzuna")
    if settings.SOURCING_REMOTE_BOARDS:
        # These accept a search term (the user's role).
        query_sources += ["remotive", "himalayas"]
    # Feed sources return their whole listing regardless of query, fetched once;
    # the per-user role/country/dedupe gates in matching filter them.
    feed_sources: list[str] = (
        ["remoteok", "arbeitnow", "weworkremotely"]
        if settings.SOURCING_REMOTE_BOARDS
        else []
    )

    if not query_sources and not feed_sources:
        log.warning("source_for_user_no_discovery_source", user_id=user_id)

    cap = settings.MAX_POSTINGS_PER_SOURCE

    def _ingest(postings: list[dict]) -> int:
        if cap > 0:
            postings = postings[:cap]
        # Never ingest an excluded company's postings for this user.
        if excluded:
            postings = [
                pp for pp in postings
                if _company_key(pp.get("company")) not in excluded
            ]
        return run_async(_persist_async(postings))

    fetched = 0
    queries = _queries_for_profile(profile)
    for source_name in query_sources:
        connector = get_connector(source_name)
        if connector is None:
            continue
        for query in queries:
            fetched += _ingest(connector.fetch(query))
    for source_name in feed_sources:
        connector = get_connector(source_name)
        if connector is not None:
            fetched += _ingest(connector.fetch({}))

    # 40, not 20: the dashboard is a user's whole pipeline, and the gates
    # (threshold + dedupe + max-per-company) already keep it relevant, so a
    # larger cap fills it faster without adding noise.
    created = run_async(match_jobs_for_user(uid, limit=40))
    log.info("source_for_user_done", user_id=user_id,
             sources=[*query_sources, *feed_sources],
             queries=len(queries), new_jobs=fetched, matched=created)
    return {"user_id": user_id, "fetched": fetched, "matched": created}


async def _profile_for(uid: uuid.UUID):
    from app.models.profile import Profile

    return await Profile.find_one(Profile.user_id == uid)


@celery.task(name="sourcing.match_for_user")
def match_for_user(user_id: str, limit: int = 20) -> dict:
    """Rank the shared Job pool for ``user_id`` and create matched applications."""
    uid = uuid.UUID(user_id)
    created = run_async(match_jobs_for_user(uid, limit=limit))  # returns an int count
    return {"user_id": user_id, "matched": created}
