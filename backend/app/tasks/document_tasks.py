"""
文档解析 Celery 任务
"""
import asyncio
from celery import Task
from app.tasks.celery_app import celery_app


class AsyncTask(Task):
    """支持 async 的 Celery 任务基类"""
    def run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)


@celery_app.task(
    name="document.parse",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="document",
)
def parse_document_task(self, document_id: str):
    """
    异步解析文档任务
    由文档上传接口触发，提取文档文本和结构化内容
    """
    import asyncio
    from app.database import AsyncSessionLocal
    from app.services.document_service import DocumentService

    async def _run():
        async with AsyncSessionLocal() as db:
            svc = DocumentService(db)
            try:
                await svc.parse_document(document_id)
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
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
    finally:
        if loop:
            loop.close()
