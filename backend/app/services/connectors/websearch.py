"""Open-web job discovery via a real search API.

This is the "search the web like a person would, then apply" source the product
is built around — NOT tied to any single job board or aggregator.

What it is:
    A query to a legitimate search API (Brave Search by default; the endpoint
    and provider are configurable) for job postings matching the user's CV. The
    results are ordinary web URLs — Greenhouse/Lever/Ashby/Workday postings,
    company career pages, wherever the role actually lives.

What it is deliberately NOT:
    It does not scrape a search-engine results PAGE (google.com/search, bing,
    the DuckDuckGo HTML endpoint). That is automating against bot detection,
    which is against those services' terms, gets the host IP blocked, and is the
    same line the apply engine holds on CAPTCHAs. A search API returns results
    to us by contract; we never pretend to be a browser hitting a search UI.

Routing to the apply engine:
    Each result's host decides ats_type. A greenhouse.io URL is tagged
    "greenhouse" so the Greenhouse adapter drives it (and, for opted-in users,
    creates the account); a bespoke company career page is tagged None and the
    apply engine parks it as "apply on the employer's site". Discovery is
    web-wide; automatic application covers the ATS-hosted majority.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors.base import JobConnector

log = get_logger(__name__)

# Host suffix -> ats_type, so a search result on a known ATS routes to the
# adapter that can actually apply on it. Kept in sync with each adapter's
# apply_hosts. Anything not here is a company-hosted page: discoverable and
# trackable, applied to manually.
_ATS_HOSTS: tuple[tuple[str, str], ...] = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
    ("myworkdayjobs.com", "workday"),
    ("workday.com", "workday"),
)

# Search results that are never a single applyable posting — aggregators,
# listicles, and index pages. Excluded so the pool fills with real postings.
_JUNK_HOSTS = (
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "monster.com", "simplyhired.com", "wikipedia.org", "youtube.com",
    "reddit.com", "quora.com", "medium.com",
)


def _ats_for_host(host: str) -> str | None:
    host = host.lower()
    for suffix, ats in _ATS_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return ats
    return None


def _company_from(host: str, title: str) -> str:
    """Best-effort company name from a result.

    Greenhouse/Lever/Ashby put the board token in the path, not the host, so we
    fall back to the second-level domain of a company site, then to the title's
    trailing "at <Company>" if present.
    """
    m = re.search(r"\bat\s+([A-Z][\w&.\- ]{1,60})$", title.strip())
    if m:
        return m.group(1).strip()
    labels = [x for x in host.lower().split(".") if x not in ("www", "jobs", "careers", "boards")]
    if len(labels) >= 2:
        return labels[-2].replace("-", " ").title()
    return host


class WebSearchConnector(JobConnector):
    """Discovers postings across the open web via a search API."""

    source = JobSource.WEB_SEARCH.value
    ats_type = None  # decided per-result by host

    # provider -> whether it needs WEB_SEARCH_API_KEY. SearXNG is self-hosted and
    # keyless; the rest are hosted APIs.
    _NEEDS_KEY = {"brave": True, "serper": True, "tavily": True, "searxng": False}

    def fetch(self, query: dict) -> list[dict]:
        """query keys: what (job title, required), where (location, optional),
        count (results, default 20)."""
        if not settings.SOURCING_WEB_SEARCH:
            return []
        provider = settings.WEB_SEARCH_PROVIDER.strip().lower()
        if self._NEEDS_KEY.get(provider, True) and not settings.WEB_SEARCH_API_KEY.strip():
            log.warning("websearch_no_api_key", provider=provider)
            return []
        what = str(query.get("what") or "").strip()
        if not what:
            return []
        where = str(query.get("where") or "").strip()
        count = self._int(query.get("count"), 20, low=1, high=20)
        terms = self._search_terms(what, where)

        # Each provider returns a list of (url, title, description) triples; the
        # posting-building, host-routing and junk-filtering below are shared, so
        # adding a provider is just one small fetch method.
        if provider == "brave":
            hits = self._brave(terms, count)
        elif provider == "serper":
            hits = self._serper(terms, count)
        elif provider == "tavily":
            hits = self._tavily(terms, count)
        elif provider == "searxng":
            hits = self._searxng(terms, count)
        else:
            log.warning("websearch_unknown_provider", provider=provider)
            return []

        postings: list[dict] = []
        seen: set[str] = set()
        for url, title, desc in hits:
            url = (url or "").strip()
            title = (title or "").strip()
            if not url or not title or url in seen:
                continue
            host = (urlparse(url).hostname or "").lower()
            if not host or any(j in host for j in _JUNK_HOSTS):
                continue
            seen.add(url)
            postings.append(
                self.to_posting(
                    source_job_id=url,  # the URL is the stable id for a web hit
                    apply_url=url,
                    company=_company_from(host, title),
                    title=re.sub(r"\s*\|\s*.*$", "", title),  # drop "| Careers" tails
                    description=desc or None,
                    ats_type=_ats_for_host(host),  # None => company-hosted, parks
                )
            )
        log.info("websearch_fetched", provider=provider, what=what, kept=len(postings))
        return postings

    def _search_terms(self, what: str, where: str) -> str:
        # Bias toward direct application pages. Broad enough to reach company
        # career sites, specific enough to skip aggregator index pages.
        loc = f" {where}" if where else ""
        return f'{what} jobs{loc} (apply OR careers OR "job application")'

    # -- providers: each returns list[(url, title, description)] --------------

    def _brave(self, terms: str, count: int) -> list[tuple]:
        endpoint = (
            settings.WEB_SEARCH_ENDPOINT
            or "https://api.search.brave.com/res/v1/web/search"
        )
        resp = self._get(
            endpoint,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": settings.WEB_SEARCH_API_KEY.strip(),
            },
            params={"q": terms, "count": count},
        )
        results = ((self._json(resp) or {}).get("web") or {}).get("results") or []
        return [
            (r.get("url"), r.get("title"), r.get("description"))
            for r in results if isinstance(r, dict)
        ]

    def _serper(self, terms: str, count: int) -> list[tuple]:
        # Serper: 2,500 free searches, no card. POST with the key in a header.
        endpoint = settings.WEB_SEARCH_ENDPOINT or "https://google.serper.dev/search"
        resp = self._post(
            endpoint,
            headers={"X-API-KEY": settings.WEB_SEARCH_API_KEY.strip()},
            json={"q": terms, "num": count},
        )
        results = (self._json(resp) or {}).get("organic") or []
        return [
            (r.get("link"), r.get("title"), r.get("snippet"))
            for r in results if isinstance(r, dict)
        ]

    def _tavily(self, terms: str, count: int) -> list[tuple]:
        # Tavily: 1,000 credits/month free. Key in the JSON body.
        endpoint = settings.WEB_SEARCH_ENDPOINT or "https://api.tavily.com/search"
        resp = self._post(
            endpoint,
            json={
                "api_key": settings.WEB_SEARCH_API_KEY.strip(),
                "query": terms,
                "max_results": count,
            },
        )
        results = (self._json(resp) or {}).get("results") or []
        return [
            (r.get("url"), r.get("title"), r.get("content"))
            for r in results if isinstance(r, dict)
        ]

    def _searxng(self, terms: str, count: int) -> list[tuple]:
        # SearXNG: self-hosted, keyless, unlimited. Point WEB_SEARCH_ENDPOINT at
        # your instance's /search. Requires JSON output enabled in its settings.
        base = settings.WEB_SEARCH_ENDPOINT or "http://searxng:8080/search"
        resp = self._get(base, params={"q": terms, "format": "json"})
        results = (self._json(resp) or {}).get("results") or []
        return [
            (r.get("url"), r.get("title"), r.get("content"))
            for r in results[:count] if isinstance(r, dict)
        ]
