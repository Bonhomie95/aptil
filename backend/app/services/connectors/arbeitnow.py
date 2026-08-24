"""Arbeitnow connector — free public JSON job board API (no key), Europe-focused."""

from __future__ import annotations

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors._ats_host import ats_for_url
from app.services.connectors.base import JobConnector

log = get_logger(__name__)


class ArbeitnowConnector(JobConnector):
    source = JobSource.ARBEITNOW.value
    ats_type = None

    BASE = "https://www.arbeitnow.com/api/job-board-api"

    def fetch(self, query: dict) -> list[dict]:
        body = self._fetch_json(self.BASE)
        rows = (body or {}).get("data") if isinstance(body, dict) else None
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
                    source_job_id=str(item.get("slug") or url),
                    apply_url=url, company=company, title=title,
                    location=item.get("location") or "Europe",
                    remote=bool(item.get("remote")),
                    description=item.get("description"),
                    posted_at=item.get("created_at"),
                    ats_type=ats_for_url(url),
                )
            )
        log.info("arbeitnow_fetched", count=len(postings))
        return postings
