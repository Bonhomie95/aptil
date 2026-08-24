"""ATS adapter registry.

``get_ats_adapter(ats_type)`` returns an adapter instance, or ``None`` when the
ATS is unsupported — in which case the caller parks the application in
``needs_info`` for manual completion (compliance section 2 / apply.py).
"""

from __future__ import annotations

from app.services.ats.ashby import AshbyAdapter
from app.services.ats.base import AtsAdapter
from app.services.ats.greenhouse import GreenhouseAdapter
from app.services.ats.lever import LeverAdapter
from app.services.ats.workday import WorkdayAdapter

# ats_type (Job.ats_type / enums.JobSource) -> adapter class.
_REGISTRY: dict[str, type[AtsAdapter]] = {
    GreenhouseAdapter.ats_type: GreenhouseAdapter,
    LeverAdapter.ats_type: LeverAdapter,
    AshbyAdapter.ats_type: AshbyAdapter,
    WorkdayAdapter.ats_type: WorkdayAdapter,
}


def get_ats_adapter(ats_type: str | None) -> AtsAdapter | None:
    """Return an adapter instance for ``ats_type``, or ``None`` if unsupported."""
    if not ats_type:
        return None
    adapter_cls = _REGISTRY.get(ats_type.strip().lower())
    return adapter_cls() if adapter_cls is not None else None


def supported_ats_types() -> list[str]:
    return sorted(_REGISTRY)


def auto_appliable_ats_types() -> list[str]:
    """ats_type values Aptil can submit end to end — for filtering the match
    scan so its budget is spent on jobs that can actually become applications,
    not diluted by company-hosted pages we would skip anyway."""
    return sorted(
        t for t, cls in _REGISTRY.items() if getattr(cls, "auto_submits", False)
    )


def can_auto_apply(ats_type: str | None) -> bool:
    """True when we can submit an application to this ATS end to end.

    Company-hosted pages (ats_type None) and park-only adapters (Workday) are
    False: matching does not turn those into applications, so the dashboard only
    ever shows jobs Aptil can actually apply to.
    """
    if not ats_type:
        return False
    cls = _REGISTRY.get(ats_type.strip().lower())
    return bool(cls and getattr(cls, "auto_submits", False))


__all__ = [
    "AtsAdapter",
    "get_ats_adapter",
    "supported_ats_types",
    "can_auto_apply",
    "auto_appliable_ats_types",
]
