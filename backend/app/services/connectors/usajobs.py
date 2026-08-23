"""USAJOBS API connector (US federal government jobs).

API: https://developer.usajobs.gov/  — requires an API key plus a User-Agent set
to the registered email. Endpoint: https://data.usajobs.gov/api/search

Federal listings are applied to on USAJOBS / agency systems, so ``ats_type``
stays None (the apply engine treats these as external-redirect postings).
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors.base import JobConnector

log = get_logger(__name__)


class USAJobsConnector(JobConnector):
    source = JobSource.USAJOBS.value
    ats_type = None

    URL = "https://data.usajobs.gov/api/search"

    def fetch(self, query: dict) -> list[dict]:
        """query keys: keyword, location (LocationName), remote (bool),
        results_per_page, page."""
        api_key = getattr(settings, "USAJOBS_API_KEY", "")
        user_agent_email = getattr(settings, "USAJOBS_USER_AGENT", "")
        if not api_key or not user_agent_email:
            log.warning("usajobs_credentials_missing")
            return []

        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": user_agent_email,
            "Authorization-Key": api_key,
        }
        params: dict = {
            "ResultsPerPage": self._int(
                query.get("results_per_page"), 50, low=1, high=500
            ),
            "Page": self._int(query.get("page"), 1, low=1, high=100),
        }
        if query.get("keyword"):
            params["Keyword"] = query["keyword"]
        if query.get("location"):
            params["LocationName"] = query["location"]
        if query.get("remote"):
            params["RemoteIndicator"] = "True"

        resp = self._get(self.URL, headers=headers, params=params)
        if resp is None:
            return []

        body = self._json(resp)
        items = ((body or {}).get("SearchResult") or {}).get("SearchResultItems") or []
        if not isinstance(items, list):
            return []

        postings: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            d = item.get("MatchedObjectDescriptor") or {}
            title = d.get("PositionTitle")
            company = d.get("OrganizationName")
            apply_uris = d.get("ApplyURI") or []
            apply_url = apply_uris[0] if apply_uris else d.get("PositionURI", "")
            if not title or not company or not apply_url:
                continue

            locations = d.get("PositionLocationDisplay")

            salary_min = salary_max = currency = None
            remuneration = d.get("PositionRemuneration") or []
            if remuneration:
                first = remuneration[0]
                raw_min = first.get("MinimumRange")
                raw_max = first.get("MaximumRange")
                try:
                    salary_min = int(float(raw_min)) if raw_min else None
                    salary_max = int(float(raw_max)) if raw_max else None
                except (TypeError, ValueError):
                    salary_min = salary_max = None
                # USAJOBS is US federal only, so pay is always USD.
                currency = "USD" if (salary_min or salary_max) else None

            description = (
                (d.get("UserArea") or {}).get("Details") or {}
            ).get("JobSummary") or d.get("QualificationSummary")

            postings.append(
                self.to_posting(
                    source_job_id=d.get("PositionID"),
                    apply_url=apply_url,
                    company=company,
                    title=title,
                    location=locations,
                    description=description,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    currency=currency,
                    posted_at=d.get("PublicationStartDate"),
                    raw=item,
                )
            )
        log.info("usajobs_fetched", count=len(postings), keyword=query.get("keyword"))
        return postings
