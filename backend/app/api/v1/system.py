"""
系统管理 API - LLM配置、系统监控
"""
import uuid
from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.database import get_db
from app.schemas.common import ResponseBase
from app.core.auth import get_current_superuser
from app.models.user import User
from app.models.system import LLMConfig, LLMProvider
from app.llm.factory import get_adapter_by_provider, get_default_llm_config, create_adapter_from_db_config

router = APIRouter(prefix="/system", tags=["系统管理"])


@router.get("/health", response_model=ResponseBase[dict], summary="健康检查", include_in_schema=False)
async def health_check(db: AsyncSession = Depends(get_db)):
    """系统健康检查端点（无需认证）"""
    status = {"api": "ok", "database": "unknown", "cache": "unknown"}
    try:
        await db.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception:
        status["database"] = "error"
    try:
        from app.core.cache import get_redis
        redis = await get_redis()
        await redis.ping()
        status["cache"] = "ok"
    except Exception:
        status["cache"] = "error"
    return ResponseBase(data=status)


@router.get("/stats", response_model=ResponseBase[dict], summary="系统统计")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    from app.models.document import Document
    from app.models.template import Template
    from app.models.extraction import ExtractionTask, TaskStatus
    from sqlalchemy import func

    doc_count = await db.execute(select(func.count(Document.id)))
    tmpl_count = await db.execute(select(func.count(Template.id)))
    task_count = await db.execute(select(func.count(ExtractionTask.id)))
    pending_tasks = await db.execute(
        select(func.count(ExtractionTask.id)).where(
            ExtractionTask.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.PROCESSING])
        )
    )
    return ResponseBase(data={
        "total_documents": doc_count.scalar(),
        "total_templates": tmpl_count.scalar(),
        "total_tasks": task_count.scalar(),
        "pending_tasks": pending_tasks.scalar(),
    })


@router.get("/llm-configs", response_model=ResponseBase[list[dict]], summary="获取LLM配置列表")
async def list_llm_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    result = await db.execute(select(LLMConfig).order_by(LLMConfig.priority.desc()))
    configs = result.scalars().all()
    return ResponseBase(data=[
        {
            "id": c.id, "name": c.name, "provider": c.provider.value,
            "model_name": c.model_name, "base_url": c.base_url,
            "is_default": c.is_default, "is_active": c.is_active,
            "last_test_success": c.last_test_success,
            "last_test_latency_ms": c.last_test_latency_ms,
        }
        for c in configs
    ])


@router.post("/llm-configs", response_model=ResponseBase[dict], summary="创建LLM配置")
async def create_llm_config(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    provider_value = payload.get("provider", "custom")
    try:
        provider = LLMProvider(provider_value)
    except ValueError:
        from app.core.exceptions import ValidationException
        raise ValidationException(f"不支持的提供商: {provider_value}")

    config = LLMConfig(
        id=str(uuid.uuid4()),
        name=payload["name"],
        provider=provider,
        model_name=payload["model_name"],
        base_url=payload.get("base_url"),
        api_key_encrypted=payload.get("api_key"),   # 生产环境应加密
        is_default=payload.get("is_default", False),
        is_active=payload.get("is_active", True),
        temperature=payload.get("temperature", 0.1),
        max_tokens=payload.get("max_tokens", 4096),
    )
    db.add(config)
    await db.flush()
    return ResponseBase(data={"id": config.id, "name": config.name})


@router.put("/llm-configs/{config_id}", response_model=ResponseBase[dict], summary="更新LLM配置")
async def update_llm_config(
    config_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    from app.core.exceptions import NotFoundException
    result = await db.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundException("LLM配置", config_id)

    updatable = ["name", "model_name", "base_url", "is_default", "is_active", "temperature", "max_tokens"]
    for field in updatable:
        if field in payload:
            setattr(config, field, payload[field])
    if payload.get("api_key"):  # 只有显式传入时才更新 key
        config.api_key_encrypted = payload["api_key"]
    if payload.get("provider"):
        try:
            config.provider = LLMProvider(payload["provider"])
        except ValueError:
            pass
    await db.flush()
    return ResponseBase(data={"id": config.id, "name": config.name})


@router.delete("/llm-configs/{config_id}", response_model=ResponseBase[dict], summary="删除LLM配置")
async def delete_llm_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    from app.core.exceptions import NotFoundException
    result = await db.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundException("LLM配置", config_id)
    await db.delete(config)
    return ResponseBase(data={"id": config_id})


@router.post("/llm-configs/{config_id}/test", response_model=ResponseBase[dict], summary="测试LLM连接")
async def test_llm_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    from datetime import datetime, timezone
    import time
    result = await db.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("LLM配置", config_id)

    start = time.time()
    success = False
    try:
        # 优先使用 DB 中存储的凭据（支持 custom 及单独配置的提供商）
        if config.base_url and config.api_key_encrypted:
            adapter = create_adapter_from_db_config(
                config.provider.value,
                config.api_key_encrypted,
                config.base_url,
            )
        else:
            adapter = get_adapter_by_provider(config.provider.value)
        success = await adapter.test_connection()
    except Exception:
        pass

    latency_ms = int((time.time() - start) * 1000)
    config.last_test_at = datetime.now(timezone.utc)
    config.last_test_success = success
    config.last_test_latency_ms = latency_ms
    await db.flush()

    return ResponseBase(data={"success": success, "latency_ms": latency_ms})
