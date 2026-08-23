"""Ashby public job-board API connector.

PUBLIC endpoint, no auth required:
    https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true

``ats_type`` is set to "ashby" so the apply engine routes to the Ashby adapter.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors.base import JobConnector

log = get_logger(__name__)


class AshbyConnector(JobConnector):
    source = JobSource.ASHBY.value
    ats_type = "ashby"

    BASE = "https://api.ashbyhq.com/posting-api/job-board"

    def fetch(self, query: dict) -> list[dict]:
        """query keys: board (the job-board name, required), company (display
        name, optional; falls back to the board name)."""
        board = str(query.get("board") or "").strip()
        if board and not re.fullmatch(r"[A-Za-z0-9_.\- ]{1,100}", board):
            log.warning("ashby_board_invalid", board=board[:50])
            return []
        if not board:
            log.warning("ashby_board_missing")
            return []
        company = query.get("company") or board

        resp = self._get(
            f"{self.BASE}/{board}", params={"includeCompensation": "true"}
        )
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
            apply_url = job.get("applyUrl") or job.get("jobUrl") or ""
            if not title or not apply_url:
                continue
            remote = job.get("isRemote")
            postings.append(
                self.to_posting(
                    source_job_id=job.get("id"),
                    apply_url=apply_url,
                    company=company,
                    title=title,
                    location=job.get("location"),
                    remote=remote if isinstance(remote, bool) else None,
                    description=job.get("descriptionPlain") or job.get("descriptionHtml"),
                    posted_at=job.get("publishedAt") or job.get("updatedAt"),
                    raw=job,
                )
            )
        log.info("ashby_fetched", count=len(postings), board=board)
        return postings
