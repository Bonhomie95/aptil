"""Job-source connector registry.

Maps a JobSource name -> connector class. Use :func:`get_connector` to resolve
a connector by source name (the value stored on ``Job.source``).
"""

from __future__ import annotations

from app.models.enums import JobSource
from app.services.connectors.adzuna import AdzunaConnector
from app.services.connectors.arbeitnow import ArbeitnowConnector
from app.services.connectors.ashby import AshbyConnector
from app.services.connectors.base import JobConnector
from app.services.connectors.greenhouse import GreenhouseConnector
from app.services.connectors.himalayas import HimalayasConnector
from app.services.connectors.lever import LeverConnector
from app.services.connectors.remoteok import RemoteOKConnector
from app.services.connectors.remotive import RemotiveConnector
from app.services.connectors.usajobs import USAJobsConnector
from app.services.connectors.websearch import WebSearchConnector
from app.services.connectors.weworkremotely import WeWorkRemotelyConnector
from app.services.connectors.workday import WorkdayConnector

CONNECTORS: dict[str, type[JobConnector]] = {
    JobSource.ADZUNA.value: AdzunaConnector,
    JobSource.GREENHOUSE.value: GreenhouseConnector,
    JobSource.LEVER.value: LeverConnector,
    JobSource.ASHBY.value: AshbyConnector,
    JobSource.USAJOBS.value: USAJobsConnector,
    JobSource.WORKDAY.value: WorkdayConnector,
    JobSource.WEB_SEARCH.value: WebSearchConnector,
    JobSource.REMOTEOK.value: RemoteOKConnector,
    JobSource.REMOTIVE.value: RemotiveConnector,
    JobSource.HIMALAYAS.value: HimalayasConnector,
    JobSource.ARBEITNOW.value: ArbeitnowConnector,
    JobSource.WEWORKREMOTELY.value: WeWorkRemotelyConnector,
}


def get_connector(name: str) -> JobConnector | None:
    """Return an instantiated connector for ``name``, or None if unknown."""
    cls = CONNECTORS.get(name)
    return cls() if cls is not None else None


__all__ = [
    "CONNECTORS",
    "get_connector",
    "JobConnector",
    "AdzunaConnector",
    "AshbyConnector",
    "GreenhouseConnector",
    "LeverConnector",
    "USAJobsConnector",
    "WorkdayConnector",
    "WebSearchConnector",
    "RemoteOKConnector",
    "RemotiveConnector",
    "HimalayasConnector",
    "ArbeitnowConnector",
    "WeWorkRemotelyConnector",
]
