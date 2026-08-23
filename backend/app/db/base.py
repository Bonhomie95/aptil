"""Beanie base documents and common field mixins.

Multi-tenancy note: MongoDB has no Row-Level Security. Isolation is enforced in the
application layer — every tenant-scoped query MUST filter by `tenant_id`. The
`TenantDocument` base carries that field; helpers/queries always constrain on it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from beanie import Document
from pydantic import Field


def _now() -> datetime:
    return datetime.now(UTC)


class TimestampedDocument(Document):
    """Base for all documents: UUID `_id` + created/updated timestamps."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()


class TenantDocument(TimestampedDocument):
    """Base for tenant-scoped documents. Always filter queries by `tenant_id`."""

    tenant_id: uuid.UUID
