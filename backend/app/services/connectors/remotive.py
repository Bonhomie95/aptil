"""Remotive connector — free public JSON API of remote jobs.

Public endpoint, no key: https://remotive.com/api/remote-jobs (supports a
`search` param). Same routing rules as the other web sources: the per-user
role/country/dedupe gates filter results, and ats_type is inferred from the
destination host.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors._ats_host import ats_for_url
from app.services.connectors.base import JobConnector

log = get_logger(__name__)

_ATS_HOSTS = (
    ("greenhouse.io", "greenhouse"), ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"), ("myworkdayjobs.com", "workday"),
)


class RemotiveConnector(JobConnector):
    source = JobSource.REMOTIVE.value
    ats_type = None

    BASE = "https://remotive.com/api/remote-jobs"

    def fetch(self, query: dict) -> list[dict]:
        params = {}
        if query.get("what"):
            params["search"] = query["what"]
        params["limit"] = self._int(query.get("limit"), 50, low=1, high=100)
        body = self._fetch_json(self.BASE, params=params)
        rows = (body or {}).get("jobs") or []
        if not isinstance(rows, list):
            return []
        postings: list[dict] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            company = (item.get("company_name") or "").strip()
            if not url or not title or not company:
                continue
            postings.append(
                self.to_posting(
                    source_job_id=str(item.get("id") or url),
                    apply_url=url,
                    company=company,
                    title=title,
                    location=item.get("candidate_required_location") or "Remote",
                    remote=True,
                    description=item.get("description"),
                    posted_at=item.get("publication_date"),
                    ats_type=ats_for_url(url),
                )
            )
        log.info("remotive_fetched", count=len(postings))
        return postings
