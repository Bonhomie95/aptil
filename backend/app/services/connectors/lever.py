"""Lever public postings API connector.

PUBLIC endpoint, no auth required:
    https://api.lever.co/v0/postings/{company}?mode=json

``ats_type`` is set to "lever" so the apply engine routes to the Lever adapter.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.enums import JobSource
from app.services.connectors.base import JobConnector

log = get_logger(__name__)


def _iso_from_ms(value: object) -> str | None:
    """Lever reports createdAt as epoch milliseconds."""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


class LeverConnector(JobConnector):
    source = JobSource.LEVER.value
    ats_type = "lever"

    BASE = "https://api.lever.co/v0/postings"

    def fetch(self, query: dict) -> list[dict]:
        """query keys: company (the Lever account slug, required), company_name
        (display name, optional; falls back to the slug)."""
        company = str(query.get("company") or "").strip()
        if company and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", company):
            log.warning("lever_company_invalid", company=company[:50])
            return []
        if not company:
            log.warning("lever_company_missing")
            return []
        company_name = query.get("company_name") or company

        resp = self._get(f"{self.BASE}/{company}", params={"mode": "json"})
        if resp is None:
            return []

        postings_raw = self._json(resp)
        if not isinstance(postings_raw, list):
            return []

        postings: list[dict] = []
        for item in postings_raw:
            if not isinstance(item, dict):
                continue
            title = item.get("text")
            # applyUrl is the form ("<hostedUrl>/apply"); hostedUrl is the
            # description page, which only has an "Apply" button on it. Filling
            # the form requires the former — this preference was backwards.
            hosted = item.get("hostedUrl") or ""
            apply_url = item.get("applyUrl") or (
                f"{hosted.rstrip('/')}/apply" if hosted else ""
            )
            if not title or not apply_url:
                continue
            categories = item.get("categories") or {}
            loc = categories.get("location")
            remote = None
            workplace = (item.get("workplaceType") or "").lower()
            if workplace:
                remote = workplace == "remote"
            # Prefer the plain-text description; fall back to HTML.
            description = item.get("descriptionPlain") or item.get("description")
            postings.append(
                self.to_posting(
                    source_job_id=item.get("id"),
                    apply_url=apply_url,
                    company=company_name,
                    title=title,
                    location=loc,
                    remote=remote,
                    description=description,
                    posted_at=_iso_from_ms(item.get("createdAt")),
                    listing_url=hosted or None,
                    raw=item,
                )
            )
        log.info("lever_fetched", count=len(postings), company=company)
        return postings
