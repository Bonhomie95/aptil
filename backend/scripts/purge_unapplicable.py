"""Delete every application Aptil could not complete (parked / failed).

    docker compose exec -T api python -m scripts.purge_unapplicable

Run once to clear legacy rows immediately; the beat schedule keeps it clean
afterwards. Never touches real applications (matched/queued/submitted/…) or
in-progress managed-account verifications.
"""

import asyncio


async def _main() -> None:
    from app.db.session import init_db
    from app.workers.tasks.scheduler import _purge_unapplicable

    await init_db()
    result = await _purge_unapplicable()
    print(f"Deleted {result['deleted']} unapplicable application(s).")


if __name__ == "__main__":
    asyncio.run(_main())
