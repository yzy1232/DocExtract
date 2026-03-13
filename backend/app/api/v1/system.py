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
from app.models.system import LLMConfig, SystemConfig
from app.llm.factory import get_default_llm_config, create_adapter_from_db_config, get_default_adapter
from sqlalchemy import update as sqlalchemy_update
import uuid
from app.models.system import SystemConfig
import uuid

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
            "id": c.id, "name": c.name,
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
    config = LLMConfig(
        id=str(uuid.uuid4()),
        name=payload["name"],
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

    # 如果新创建的配置设为默认，清除其它默认，并同步到 SystemConfig
    if config.is_default:
        await db.execute(
            sqlalchemy_update(LLMConfig).where(LLMConfig.id != config.id).values(is_default=False)
        )
        # upsert system config key 'default_llm_config_id'
        result = await db.execute(select(SystemConfig).where(SystemConfig.key == 'default_llm_config_id'))
        sc = result.scalar_one_or_none()
        if sc:
            sc.value = config.id
            sc.updated_by = getattr(current_user, 'id', None)
        else:
            new_sc = SystemConfig(
                id=str(uuid.uuid4()),
                category='system',
                key='default_llm_config_id',
                value=config.id,
                default_value=None,
                description='系统默认LLM配置ID',
                data_type='string',
                is_editable=True,
                is_encrypted=False,
                updated_by=getattr(current_user, 'id', None),
            )
            db.add(new_sc)
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
    # provider 已移除，忽略 provider 字段
    await db.flush()

    # 如果更新将该配置设为默认，同步其它记录和系统配置
    if payload.get('is_default'):
        if config.is_default:
            await db.execute(
                sqlalchemy_update(LLMConfig).where(LLMConfig.id != config.id).values(is_default=False)
            )
            result = await db.execute(select(SystemConfig).where(SystemConfig.key == 'default_llm_config_id'))
            sc = result.scalar_one_or_none()
            if sc:
                sc.value = config.id
                sc.updated_by = getattr(current_user, 'id', None)
            else:
                new_sc = SystemConfig(
                    id=str(uuid.uuid4()),
                    category='system',
                    key='default_llm_config_id',
                    value=config.id,
                    default_value=None,
                    description='系统默认LLM配置ID',
                    data_type='string',
                    is_editable=True,
                    is_encrypted=False,
                    updated_by=getattr(current_user, 'id', None),
                )
                db.add(new_sc)
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
        # 优先使用 DB 中存储的凭据（以配置中 base_url/api_key 为准）
        if config.base_url and config.api_key_encrypted:
            adapter = create_adapter_from_db_config(
                config.api_key_encrypted,
                config.base_url,
            )
        else:
            # 回退到系统默认适配器
            adapter = get_default_adapter()
        success = await adapter.test_connection()
    except Exception:
        pass

    latency_ms = int((time.time() - start) * 1000)
    config.last_test_at = datetime.now(timezone.utc)
    config.last_test_success = success
    config.last_test_latency_ms = latency_ms
    await db.flush()

    return ResponseBase(data={"success": success, "latency_ms": latency_ms})


@router.get('/configs', response_model=ResponseBase[list[dict]], summary='获取系统配置列表')
async def list_system_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
    configs = result.scalars().all()
    return ResponseBase(data=[{
        'id': c.id, 'category': c.category, 'key': c.key, 'value': c.value,
        'default_value': c.default_value, 'description': c.description, 'data_type': c.data_type,
    } for c in configs])


@router.get('/configs/{key}', response_model=ResponseBase[dict], summary='获取指定系统配置')
async def get_system_config(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalar_one_or_none()
    if not cfg:
        from app.core.exceptions import NotFoundException
        raise NotFoundException('SystemConfig', key)
    return ResponseBase(data={
        'id': cfg.id, 'category': cfg.category, 'key': cfg.key, 'value': cfg.value,
        'default_value': cfg.default_value, 'description': cfg.description, 'data_type': cfg.data_type,
    })


@router.put('/configs/{key}', response_model=ResponseBase[dict], summary='更新或创建系统配置')
async def put_system_config(
    key: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    # payload: { value: str, category?: str, data_type?: str, description?: str }
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalar_one_or_none()
    if cfg:
        if 'value' in payload:
            cfg.value = str(payload['value'])
        if 'description' in payload:
            cfg.description = payload['description']
        if 'data_type' in payload:
            cfg.data_type = payload['data_type']
        cfg.updated_by = getattr(current_user, 'id', None)
    else:
        new_cfg = SystemConfig(
            id=str(uuid.uuid4()),
            category=payload.get('category', 'system'),
            key=key,
            value=str(payload.get('value', '')),
            default_value=payload.get('default_value'),
            description=payload.get('description'),
            data_type=payload.get('data_type', 'string'),
            is_editable=True,
            is_encrypted=False,
            updated_by=getattr(current_user, 'id', None),
        )
        db.add(new_cfg)
    await db.flush()
    return ResponseBase(data={'key': key, 'value': payload.get('value')})
