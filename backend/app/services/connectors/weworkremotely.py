"""WeWorkRemotely connector — free public RSS feeds (no key).

WWR has no JSON API but publishes category RSS feeds. We parse the XML with the
stdlib (defusedxml would be ideal, but the feed is our own trusted source and
we only read text). Browser fallback applies if the direct fetch is blocked.
"""

from __future__ import annotations

import re

import defusedxml.ElementTree as ET  # safe parser for untrusted RSS

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors._ats_host import ats_for_url
from app.services.connectors.base import JobConnector

log = get_logger(__name__)

# A few high-traffic category feeds. WWR titles are "Company: Role".
_FEEDS = (
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
)


class WeWorkRemotelyConnector(JobConnector):
    source = JobSource.WEWORKREMOTELY.value
    ats_type = None

    def fetch(self, query: dict) -> list[dict]:
        postings: list[dict] = []
        for feed in _FEEDS:
            postings.extend(self._parse_feed(feed))
        log.info("weworkremotely_fetched", count=len(postings))
        return postings

    def _parse_feed(self, url: str) -> list[dict]:
        resp = self._get(url)
        text = resp.text if resp is not None else self._browser_fetch_text(url)
        if not text:
            return []
        try:
            root = ET.fromstring(text)
        except Exception:  # defusedxml raises on malformed OR malicious XML
            log.warning("wwr_bad_xml", url=url)
            return []
        out: list[dict] = []
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            raw_title = (item.findtext("title") or "").strip()
            if not link or not raw_title:
                continue
            # "Company: Role Title" -> split once.
            company, _, role = raw_title.partition(":")
            company = company.strip()
            role = (role or raw_title).strip()
            if not company or not role:
                continue
            out.append(
                self.to_posting(
                    source_job_id=link,
                    apply_url=link, company=company, title=role,
                    location="Remote", remote=True,
                    description=re.sub(r"<[^>]+>", " ",
                                       item.findtext("description") or "")[:5000],
                    posted_at=item.findtext("pubDate"),
                    ats_type=ats_for_url(link),
                )
            )
        return out
