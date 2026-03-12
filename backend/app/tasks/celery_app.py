"""
Celery 应用实例配置
"""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "docextract",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.extraction_tasks",
    ],
)

celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=True,
    # 任务路由
    task_routes={
        "app.tasks.document_tasks.*": {"queue": "document"},
        "app.tasks.extraction_tasks.*": {"queue": "extraction"},
    },
    # 任务超时
    task_soft_time_limit=300,
    task_time_limit=600,
    # 重试配置
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 结果保留时间
    result_expires=3600 * 24,
    # Worker 并发
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.CELERY_MAX_WORKERS,
    # 保持与未来 Celery 版本的兼容：在启动时重试 broker 连接
    broker_connection_retry_on_startup=True,
    # 使 worker 发布事件，以便 Flower 能够通过 inspector 获取队列/任务状态
    worker_send_task_events=True,
    task_send_sent_event=True,
)
