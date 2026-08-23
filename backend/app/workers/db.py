"""Worker-side DB access.

Celery tasks are sync; Beanie is async. Tasks wrap their async body in `run_async`,
which reuses one event loop per worker process and initializes Beanie once. Example:

    from app.workers.db import run_async

    @celery.task
    def my_task(doc_id: str):
        return run_async(_my_task_async(doc_id))

    async def _my_task_async(doc_id: str):
        doc = await SomeModel.get(uuid.UUID(doc_id))
        ...
"""

from app.db.session import run_async

__all__ = ["run_async"]
