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


__all__ = ["AtsAdapter", "get_ats_adapter", "supported_ats_types"]
