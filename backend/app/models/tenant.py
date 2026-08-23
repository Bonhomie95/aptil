"""Tenant: the top-level isolation boundary. Each customer account is a tenant."""

from __future__ import annotations

from app.db.base import TimestampedDocument


class Tenant(TimestampedDocument):
    name: str

    class Settings:
        name = "tenants"
