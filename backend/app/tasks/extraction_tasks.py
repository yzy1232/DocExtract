"""
提取任务 Celery Worker
"""
import asyncio
from app.tasks.celery_app import celery_app


@celery_app.task(
    name="extraction.run",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    queue="extraction",
)
def run_extraction_task(self, task_id: str):
    """
    执行 LLM 提取任务
    由提取接口触发，调用 LLM 从文档中提取模板定义的字段
    """
    from app.database import AsyncSessionLocal
    from app.services.extraction_service import ExtractionService

    async def _run():
        async with AsyncSessionLocal() as db:
            svc = ExtractionService(db)
            try:
                await svc.execute_extraction(task_id)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
    finally:
        if loop:
            loop.close()
