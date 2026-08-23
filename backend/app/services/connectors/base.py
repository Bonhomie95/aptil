"""Base class for job-source connectors.

Connectors pull from LEGITIMATE sources only — official APIs and public ATS
endpoints / job feeds (see docs/compliance.md). Each connector normalizes its
provider's payload into the plain dict shape that
``app.workers.tasks.discovery.upsert_job`` / ``ingest_postings`` expect, so the
apply engine can route by ``ats_type``.

Normalized posting keys:
    source, source_job_id, apply_url, ats_type, company, title, location,
    remote, description, salary_min, salary_max, currency, posted_at, raw
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 20.0
# Identify honestly (compliance §6: be a polite automated client).
USER_AGENT = "AptilJobConnector/1.0 (+https://aptil.ai)"


class JobConnector(ABC):
    """Abstract base for a single job source.

    Subclasses set ``source`` (a JobSource value) and, where the postings are
    applied to through a known ATS, ``ats_type`` so the apply engine can pick
    the right adapter. Implement :meth:`fetch`.
    """

    #: JobSource enum value, e.g. "greenhouse".
    source: str = "other"
    #: ATS the apply engine routes to, or None for aggregators (e.g. Adzuna).
    ats_type: str | None = None

    @abstractmethod
    def fetch(self, query: dict) -> list[dict]:
        """Return a list of normalized postings for ``query``.

        Implementations MUST be resilient: wrap network calls and return ``[]``
        on any failure (never raise into the caller). Map only fields the API
        actually returns — do not invent data.
        """
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------

    def _get(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """GET with a sane timeout + honest UA. Returns None on any failure.

        Catches broadly on purpose: the contract with ``fetch`` is that a
        connector never raises into the scheduler, and non-HTTPError failures
        (bad URL, DNS, TLS, malformed params) are just as fatal to a batch.
        """
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        try:
            resp = httpx.get(
                url,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001 - never raise into the caller
            log.warning(
                "connector_fetch_failed",
                source=self.source,
                url=url,
                error=str(exc)[:300],
            )
            return None

    def _post(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """POST with the same guarantees as :meth:`_get`.

        Some careers sites (Workday) expose their public listing feed as a POST
        with a JSON body rather than a query string.
        """
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        try:
            resp = httpx.post(
                url,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001 - never raise into the caller
            log.warning(
                "connector_fetch_failed",
                source=self.source,
                url=url,
                error=str(exc)[:300],
            )
            return None

    def _json(self, resp: httpx.Response | None) -> Any:
        """Parse JSON defensively; returns None when the body is not JSON."""
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            log.warning("connector_bad_json", source=self.source)
            return None

    @staticmethod
    def _int(value: Any, default: int, *, low: int, high: int) -> int:
        """Clamp a caller-supplied query value into a sane range."""
        try:
            return max(low, min(int(value), high))
        except (TypeError, ValueError):
            return default

    def to_posting(
        self,
        *,
        source_job_id: str | None,
        apply_url: str,
        company: str,
        title: str,
        location: str | None = None,
        remote: bool | None = None,
        description: str | None = None,
        salary_min: int | None = None,
        salary_max: int | None = None,
        currency: str | None = None,
        posted_at: str | None = None,
        ats_type: str | None = None,
        listing_url: str | None = None,
        raw: dict | None = None,
    ) -> dict:
        """Assemble a normalized posting dict.

        ``source`` and ``ats_type`` default to the connector's class attributes;
        pass ``ats_type`` to override per-posting.
        """
        return {
            "source": self.source,
            "source_job_id": str(source_job_id) if source_job_id is not None else None,
            "apply_url": apply_url,
            "listing_url": listing_url,
            "ats_type": ats_type if ats_type is not None else self.ats_type,
            "company": company,
            "title": title,
            "location": location,
            "remote": remote,
            "description": description,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "currency": currency,
            "posted_at": posted_at,
            "raw": raw or {},
        }
