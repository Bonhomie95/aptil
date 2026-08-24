"""Shared host -> ats_type routing for open-web/board connectors.

A posting's apply URL host decides which apply adapter (if any) can drive it.
Kept in one place so every connector routes identically.
"""

from __future__ import annotations

from urllib.parse import urlparse

_ATS_HOSTS: tuple[tuple[str, str], ...] = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
    ("myworkdayjobs.com", "workday"),
    ("workday.com", "workday"),
)


def ats_for_url(url: str) -> str | None:
    host = (urlparse(url or "").hostname or "").lower()
    for suffix, ats in _ATS_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return ats
    return None
