"""Diagnostic instrumentation: logs every delete command issued against
watched MongoDB collections, with a Python stack trace of what issued it.

Exists because a JobApplication row (status "needs_info", meant to be kept
indefinitely — see JobApplication.job_snapshot) was found deleted with no
trace in application logs, and an exhaustive code review found no code path
that explains it. Every known deletion path in this codebase already logs
(application_discarded, purged_unapplicable) or was ruled out directly, so
this hooks at the PyMongo command level instead — below the ODM, below any
specific service module — so it catches a delete regardless of which code
issued it, including a path this review might have missed. If the mystery
recurs, this is what actually catches it in the act.

Temporary: safe to remove once the cause is found and fixed. Overhead is
negligible — one cheap collection-name check per command, and a stack trace
capture only for delete commands against a watched collection.
"""

from __future__ import annotations

import traceback

from pymongo import monitoring

from app.core.logging import get_logger

log = get_logger(__name__)

# Add a collection name here to start auditing deletes against it too.
_WATCHED_COLLECTIONS = {"job_applications"}


class _DeleteAuditListener(monitoring.CommandListener):
    def started(self, event: monitoring.CommandStartedEvent) -> None:
        # `delete` (deleteMany/deleteOne via the bulk API) and `findAndModify`
        # (an atomic find-and-delete) are the only commands that remove
        # documents. The collection name is the command's own value, not a
        # separate attribute — e.g. {"delete": "job_applications", ...}.
        if event.command_name not in ("delete", "findAndModify"):
            return
        collection = event.command.get(event.command_name)
        if collection not in _WATCHED_COLLECTIONS:
            return

        if event.command_name == "delete":
            deletes = event.command.get("deletes") or []
            filters = [d.get("q") for d in deletes]
            limits = [d.get("limit") for d in deletes]
        else:  # findAndModify with remove=true
            filters = [event.command.get("query")]
            limits = [1]

        # Trim the frames inside this listener itself; what matters is the
        # caller's path through the app.
        stack = "".join(traceback.format_stack()[:-1])
        log.warning(
            "watched_collection_delete_command",
            collection=collection,
            command=event.command_name,
            filters=filters,
            limits=limits,
            request_id=event.request_id,
            stack=stack,
        )

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        if event.command_name not in ("delete", "findAndModify"):
            return
        reply = event.reply or {}
        deleted = reply.get("n") if event.command_name == "delete" else (
            1 if (reply.get("lastErrorObject") or {}).get("n") else 0
        )
        if deleted:
            log.warning(
                "watched_collection_delete_succeeded",
                command=event.command_name,
                request_id=event.request_id,
                deleted_count=deleted,
            )

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass


_registered = False


def register() -> None:
    """Idempotent — safe to call from both the API and worker entry points."""
    global _registered
    if _registered:
        return
    monitoring.register(_DeleteAuditListener())
    _registered = True
