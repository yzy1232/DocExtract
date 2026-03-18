"""
Celery 应用实例配置
"""
from celery import Celery
from app.config import settings
import re

def _sanitize_redis_url(url: str) -> str:
    if not url:
        return url
    # 修复因空密码导致的 redis://:@host 格式问题
    if url.startswith("redis://") and "@" in url:
        # 将 'redis://:@host' 或 'redis://:@' 等替换为 'redis://host' 或 'redis://'
        url = url.replace("redis://:@", "redis://")
    return url

celery_app = Celery(
    "docextract",
    broker=_sanitize_redis_url(settings.CELERY_BROKER_URL),
    backend=_sanitize_redis_url(settings.CELERY_RESULT_BACKEND),
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
    # 任务超时（增加到30分钟以支持复杂文档处理）
    task_soft_time_limit=1800,  # 30分钟
    task_time_limit=3600,  # 60分钟（硬限制）
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
    # Redis 传输配置：worker 异常退出后，任务在超时后可重新投递，避免长期卡在 unacked。
    broker_transport_options={
        "visibility_timeout": 300,
    },
    # 使 worker 发布事件，以便 Flower 能够通过 inspector 获取队列/任务状态
    worker_send_task_events=True,
    task_send_sent_event=True,
)
