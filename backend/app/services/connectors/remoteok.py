"""RemoteOK connector — free public JSON feed of remote jobs.

Public endpoint, no key: https://remoteok.com/api (first array element is a
legal/attribution notice, skipped). RemoteOK asks for a backlink, which we
honour by keeping their canonical URL as the apply/listing URL.

These are aggregated remote postings; the per-user role, country and dedupe
gates in matching decide which reach any given user. ats_type stays None (the
url is the employer's own page or RemoteOK's redirect), so the apply engine
parks them for the user unless the destination is a known ATS.
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


class RemoteOKConnector(JobConnector):
    source = JobSource.REMOTEOK.value
    ats_type = None

    BASE = "https://remoteok.com/api"

    def fetch(self, query: dict) -> list[dict]:
        rows = self._fetch_json(self.BASE)
        if not isinstance(rows, list):
            return []
        postings: list[dict] = []
        for item in rows:
            if not isinstance(item, dict) or "position" not in item:
                continue  # skips the leading legal-notice element
            url = (item.get("url") or item.get("apply_url") or "").strip()
            title = (item.get("position") or "").strip()
            company = (item.get("company") or "").strip()
            if not url or not title or not company:
                continue
            postings.append(
                self.to_posting(
                    source_job_id=str(item.get("id") or url),
                    apply_url=url,
                    company=company,
                    title=title,
                    location=item.get("location") or "Remote",
                    remote=True,
                    description=item.get("description"),
                    posted_at=item.get("date"),
                    ats_type=ats_for_url(url),
                )
            )
        log.info("remoteok_fetched", count=len(postings))
        return postings
