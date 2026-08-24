"""Himalayas connector — free public JSON API of remote jobs (no key).

Endpoints: /jobs/api (browse, max 20) and /jobs/api/search?search=... . Rate
limited, so we keep requests small and rely on the browser fallback only if the
direct fetch is blocked.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors._ats_host import ats_for_url
from app.services.connectors.base import JobConnector

log = get_logger(__name__)


class HimalayasConnector(JobConnector):
    source = JobSource.HIMALAYAS.value
    ats_type = None

    BROWSE = "https://himalayas.app/jobs/api"
    SEARCH = "https://himalayas.app/jobs/api/search"

    def fetch(self, query: dict) -> list[dict]:
        what = str(query.get("what") or "").strip()
        if what:
            body = self._fetch_json(self.SEARCH, params={"search": what})
        else:
            body = self._fetch_json(self.BROWSE, params={"limit": 20})
        rows = (body or {}).get("jobs") if isinstance(body, dict) else body
        if not isinstance(rows, list):
            return []
        postings: list[dict] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            url = (item.get("applicationLink") or "").strip()
            title = (item.get("title") or "").strip()
            company = (item.get("companyName") or "").strip()
            if not url or not title or not company:
                continue
            loc = item.get("locationRestrictions")
            if isinstance(loc, list):
                loc = ", ".join(str(x) for x in loc) or "Remote"
            postings.append(
                self.to_posting(
                    source_job_id=str(item.get("guid") or url),
                    apply_url=url, company=company, title=title,
                    location=loc or "Remote", remote=True,
                    description=item.get("description"),
                    posted_at=item.get("pubDate"),
                    ats_type=ats_for_url(url),
                )
            )
        log.info("himalayas_fetched", count=len(postings))
        return postings
