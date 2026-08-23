"""Greenhouse public job-board API connector.

PUBLIC endpoint, no auth required:
    https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true

``ats_type`` is set to "greenhouse" so the apply engine routes to the Greenhouse
ATS adapter.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors.base import JobConnector

log = get_logger(__name__)


class GreenhouseConnector(JobConnector):
    source = JobSource.GREENHOUSE.value
    ats_type = "greenhouse"

    BASE = "https://boards-api.greenhouse.io/v1/boards"

    def fetch(self, query: dict) -> list[dict]:
        """query keys: board (the board token, required), company (display name,
        optional; falls back to the board token)."""
        board = str(query.get("board") or "").strip()
        # Board tokens go into the path; keep them to a safe charset.
        if board and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", board):
            log.warning("greenhouse_board_invalid", board=board[:50])
            return []
        if not board:
            log.warning("greenhouse_board_missing")
            return []
        company = query.get("company") or board

        resp = self._get(f"{self.BASE}/{board}/jobs", params={"content": "true"})
        if resp is None:
            return []

        body = self._json(resp)
        jobs = (body or {}).get("jobs") or []
        if not isinstance(jobs, list):
            return []

        postings: list[dict] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            title = job.get("title")
            job_id = job.get("id")
            # `absolute_url` is whatever the employer configured, and for most
            # large boards that is their OWN careers site — Stripe's resolves to
            # stripe.com/careers, which has no form on the page at all. The
            # canonical Greenhouse-hosted form is derivable from the board token
            # and job id, and returns 200 even for those employers, so prefer it
            # and keep absolute_url only as a fallback.
            apply_url = (
                f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}"
                if job_id
                else (job.get("absolute_url") or "")
            )
            if not title or not apply_url:
                continue
            loc = (job.get("location") or {}).get("name")
            postings.append(
                self.to_posting(
                    source_job_id=job.get("id"),
                    apply_url=apply_url,
                    company=company,
                    title=title,
                    location=loc,
                    description=job.get("content"),
                    posted_at=job.get("updated_at") or job.get("first_published"),
                    listing_url=job.get("absolute_url") or None,
                    raw=job,
                )
            )
        log.info("greenhouse_fetched", count=len(postings), board=board)
        return postings
