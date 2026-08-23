"""Adzuna job-search API connector.

Adzuna is an aggregator, not an ATS — the normalized ``ats_type`` stays None so
the apply engine treats these as external-redirect postings.

API: https://developer.adzuna.com/  (needs app_id + app_key)
Endpoint: https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors.base import JobConnector

log = get_logger(__name__)


# Countries Adzuna actually serves (https://developer.adzuna.com/overview).
# A query to any other country 404s, so the UI must only offer these.
ADZUNA_COUNTRIES: dict[str, str] = {
    "gb": "United Kingdom", "us": "United States", "at": "Austria",
    "au": "Australia", "be": "Belgium", "br": "Brazil", "ca": "Canada",
    "ch": "Switzerland", "de": "Germany", "es": "Spain", "fr": "France",
    "in": "India", "it": "Italy", "mx": "Mexico", "nl": "Netherlands",
    "nz": "New Zealand", "pl": "Poland", "sg": "Singapore", "za": "South Africa",
}

# Continent groupings, so a user can pick a region instead of ticking countries.
ADZUNA_CONTINENTS: dict[str, list[str]] = {
    "north_america": ["us", "ca", "mx"],
    "south_america": ["br"],
    "europe": ["gb", "at", "be", "ch", "de", "es", "fr", "it", "nl", "pl"],
    "asia": ["in", "sg"],
    "oceania": ["au", "nz"],
    "africa": ["za"],
}


def resolve_countries(values: list[str]) -> list[str]:
    """Expand a mix of ISO-2 codes and continent names into valid ISO-2 codes.

    Unknown entries are dropped, order preserved, deduped. So the UI can send
    ["europe", "us"] and get every European country plus the US.
    """
    out: list[str] = []
    for raw in values or []:
        key = str(raw).strip().lower()
        if key in ADZUNA_CONTINENTS:
            out.extend(ADZUNA_CONTINENTS[key])
        elif key in ADZUNA_COUNTRIES:
            out.append(key)
    seen: set[str] = set()
    return [c for c in out if not (c in seen or seen.add(c))]


class AdzunaConnector(JobConnector):
    source = JobSource.ADZUNA.value
    ats_type = None  # aggregator: apply_url redirects out to the source

    BASE = "https://api.adzuna.com/v1/api/jobs"

    def fetch(self, query: dict) -> list[dict]:
        """query keys: what (keywords), where (location), country (iso2, default 'gb'),
        page, results_per_page, remote (bool)."""
        app_id = getattr(settings, "ADZUNA_APP_ID", "")
        app_key = getattr(settings, "ADZUNA_APP_KEY", "")
        if not app_id or not app_key:
            log.warning("adzuna_credentials_missing")
            return []

        country = str(query.get("country") or "gb").lower()[:2]
        if not country.isalpha():
            country = "gb"
        page = self._int(query.get("page"), 1, low=1, high=100)
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": self._int(
                query.get("results_per_page"), 50, low=1, high=50
            ),
            "content-type": "application/json",
        }
        if query.get("what"):
            params["what"] = query["what"]
        if query.get("where"):
            params["where"] = query["where"]

        resp = self._get(f"{self.BASE}/{country}/search/{page}", params=params)
        if resp is None:
            return []

        body = self._json(resp)
        results = (body or {}).get("results") or []
        if not isinstance(results, list):
            return []

        postings: list[dict] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            company = (item.get("company") or {}).get("display_name")
            title = item.get("title")
            apply_url = item.get("redirect_url") or ""
            # Without a destination the posting is useless to the apply engine.
            if not company or not title or not apply_url:
                continue
            loc = (item.get("location") or {}).get("display_name")
            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")
            postings.append(
                self.to_posting(
                    source_job_id=item.get("id"),
                    apply_url=apply_url,
                    company=company,
                    title=title,
                    location=loc,
                    description=item.get("description"),
                    salary_min=int(salary_min) if salary_min is not None else None,
                    salary_max=int(salary_max) if salary_max is not None else None,
                    # Adzuna reports salaries in the country currency; not always
                    # returned per-item, so leave None unless present.
                    currency=item.get("salary_currency"),
                    posted_at=item.get("created"),
                    raw=item,
                )
            )
        log.info("adzuna_fetched", count=len(postings), what=query.get("what"))
        return postings
