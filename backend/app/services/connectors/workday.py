"""Workday (myworkdayjobs) connector.

Workday has no public cross-tenant search API. Each customer's careers site
exposes the same JSON endpoint its own front end calls:

    POST https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
         {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

That is the site's own public feed — the same data the careers page renders, no
auth, no login, no scraping of a signed-in session (compliance section 1). We
send an honest User-Agent and take one page per run.

Unlike Greenhouse/Lever/Ashby, Workday postings cannot be applied to
anonymously: the form is behind a sign-in. Discovery therefore only pays off for
users who have stored a credential for the tenant's careers host — see
``WorkdayAdapter``. Postings still surface in the dashboard either way; the
apply engine parks them with ``credential_required`` if there is no credential.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors.base import JobConnector

log = get_logger(__name__)

# Tenant/site tokens go into a URL path — keep them to a safe charset.
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Workday data centres seen in careers URLs (wd1.myworkdayjobs.com etc.).
_DC = re.compile(r"wd\d{1,3}")

MAX_POSTINGS = 100
PAGE_SIZE = 20


class WorkdayConnector(JobConnector):
    source = JobSource.WORKDAY.value
    ats_type = "workday"

    def fetch(self, query: dict) -> list[dict]:
        """query keys: tenant (required), site (required), dc (default "wd1"),
        company (display name, optional), search (optional free text)."""
        tenant = str(query.get("tenant") or "").strip()
        site = str(query.get("site") or "").strip()
        dc = str(query.get("dc") or "wd1").strip()
        if not (_TOKEN.fullmatch(tenant) and _TOKEN.fullmatch(site) and _DC.fullmatch(dc)):
            log.warning("workday_query_invalid", tenant=tenant[:40], site=site[:40])
            return []

        company = query.get("company") or tenant
        host = f"https://{tenant}.{dc}.myworkdayjobs.com"
        endpoint = f"{host}/wday/cxs/{tenant}/{site}/jobs"

        postings: list[dict] = []
        offset = 0
        while len(postings) < MAX_POSTINGS:
            resp = self._post(
                endpoint,
                json={
                    "appliedFacets": {},
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "searchText": str(query.get("search") or ""),
                },
                headers={"Accept": "application/json"},
            )
            if resp is None:
                break
            body = self._json(resp) or {}
            batch = body.get("jobPostings") or []
            if not isinstance(batch, list) or not batch:
                break
            postings.extend(self._normalise(batch, host, site, company))
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        log.info("workday_fetched", count=len(postings), tenant=tenant, site=site)
        return postings[:MAX_POSTINGS]

    def _normalise(
        self, batch: list[Any], host: str, site: str, company: str
    ) -> list[dict]:
        out: list[dict] = []
        for job in batch:
            if not isinstance(job, dict):
                continue
            title = job.get("title")
            # externalPath is site-relative, e.g. "/job/London/Engineer_R-123".
            path = job.get("externalPath") or ""
            if not title or not path:
                continue
            location = job.get("locationsText") or job.get("locationText")
            out.append(
                self.to_posting(
                    source_job_id=job.get("bulletFields", [None])[0] or path,
                    apply_url=f"{host}/en-US/{site}{path}",
                    company=company,
                    title=title,
                    location=location,
                    # The list endpoint carries no description; matching falls
                    # back to title + skills rather than inventing one.
                    description=None,
                    posted_at=job.get("postedOn"),
                    raw=job,
                )
            )
        return out
