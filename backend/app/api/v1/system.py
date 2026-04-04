"""
系统管理 API - LLM配置、系统监控
"""
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, or_, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.schemas.common import ResponseBase
from app.core.auth import get_current_superuser, get_current_user
from app.models.user import User, Role, UserStatus
from app.models.system import LLMConfig, SystemConfig
from app.schemas.user import AdminUserCreate, AdminUserUpdate
from app.core.security import hash_password
from app.llm.factory import get_default_llm_config, create_adapter_from_db_config, get_default_adapter
from app.core.disaster_recovery import detect_disaster_state, run_emergency_repair
from app.config import settings
from sqlalchemy import update as sqlalchemy_update

router = APIRouter(prefix="/system", tags=["系统管理"])

logger = logging.getLogger("app.api.v1.system")


def _ensure_emergency_public_api_enabled() -> None:
    from app.core.exceptions import ForbiddenException

    if not settings.EMERGENCY_PUBLIC_API_ENABLED:
        raise ForbiddenException("应急公共接口已禁用")


async def _execute_disaster_repair(payload: dict) -> dict:
    from app.core.exceptions import ValidationException

    dry_run = bool(payload.get("dry_run", False))
    expected_confirm = str(settings.EMERGENCY_REPAIR_CONFIRM_TOKEN or "REBUILD").strip()
    provided_confirm = str(payload.get("confirm") or "").strip()

    if not dry_run and provided_confirm != expected_confirm:
        raise ValidationException(f"高危操作确认失败，请输入确认口令: {expected_confirm}")

    try:
        scan_limit = int(payload.get("scan_limit", settings.DISASTER_RECOVERY_SCAN_LIMIT))
    except (TypeError, ValueError):
        raise ValidationException("scan_limit 必须是整数")

    return await run_emergency_repair(
        rebuild_database=bool(payload.get("rebuild_database", True)),
        rebuild_redis=bool(payload.get("rebuild_redis", True)),
        recover_documents=bool(payload.get("recover_documents", True)),
        promote_redis_to_master=bool(payload.get("promote_redis_to_master", True)),
        restart_runtime=bool(payload.get("restart_runtime", True)),
        dry_run=dry_run,
        scan_limit=scan_limit,
    )


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status.value if hasattr(user.status, "value") else str(user.status),
        "is_superuser": user.is_superuser,
        "roles": [
            {
                "id": role.id,
                "name": role.name,
                "display_name": role.display_name,
                "description": role.description,
            }
            for role in (user.roles or [])
        ],
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


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

    try:
        report = await detect_disaster_state(db=db, detailed=False)
        status["disaster"] = {
            "severity": report.get("severity", "unknown"),
            "has_critical": bool(report.get("has_critical")),
            "risk_count": len(report.get("risk_items") or []),
        }
    except Exception:
        status["disaster"] = {
            "severity": "unknown",
            "has_critical": False,
            "risk_count": 0,
        }

    return ResponseBase(data=status)


@router.get("/disaster-check", response_model=ResponseBase[dict], summary="极端情况检测")
async def disaster_check(
    _current_user: User = Depends(get_current_superuser),
):
    """检测数据库/Redis 异常与弱配置风险。"""
    report = await detect_disaster_state(detailed=True)
    return ResponseBase(data=report)


@router.post("/disaster-repair", response_model=ResponseBase[dict], summary="极端情况修复与重载")
async def disaster_repair(
    payload: dict = Body(...),
    _current_user: User = Depends(get_current_superuser),
):
    """执行高危修复：可选重建数据库、重建 Redis、恢复部分文档、运行时重载。"""
    report = await _execute_disaster_repair(payload)
    return ResponseBase(data=report)


@router.get(
    "/public-disaster-check",
    response_model=ResponseBase[dict],
    summary="公共极端情况检测",
    include_in_schema=False,
)
async def public_disaster_check(
):
    """登录失败场景使用：无需登录。"""
    _ensure_emergency_public_api_enabled()
    report = await detect_disaster_state(detailed=True)
    return ResponseBase(data=report)


@router.post(
    "/public-disaster-repair",
    response_model=ResponseBase[dict],
    summary="公共极端情况修复",
    include_in_schema=False,
)
async def public_disaster_repair(
    payload: dict = Body(...),
):
    """登录失败场景使用：仅在检测到严重异常时允许执行。"""
    from app.core.exceptions import ForbiddenException

    _ensure_emergency_public_api_enabled()
    state = await detect_disaster_state(detailed=False)
    if not state.get("has_critical"):
        raise ForbiddenException("当前服务未处于异常状态，禁止执行公共应急修复")

    report = await _execute_disaster_repair(payload)
    return ResponseBase(data=report)


@router.get("/stats", response_model=ResponseBase[dict], summary="系统统计")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.document import Document
    from app.models.template import Template
    from app.models.extraction import ExtractionTask, TaskStatus

    # 统计时排除已删除/归档的数据以符合前端显示语义（活跃模板、未删除文档）
    from app.models.document import DocumentStatus
    from app.models.template import TemplateStatus

    doc_stmt = select(func.count(Document.id)).where(Document.status != DocumentStatus.DELETED)
    tmpl_stmt = select(func.count(Template.id)).where(Template.status != TemplateStatus.ARCHIVED)
    task_stmt = select(func.count(ExtractionTask.id))
    pending_stmt = select(func.count(ExtractionTask.id)).where(
        ExtractionTask.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.PROCESSING, TaskStatus.RETRYING])
    )

    # 管理员看全局；普通用户仅看自己创建/上传的数据。
    if not current_user.is_superuser:
                doc_stmt = doc_stmt.where(Document.owner_id == current_user.id)
                tmpl_stmt = tmpl_stmt.where(Template.creator_id == current_user.id)
                task_stmt = task_stmt.where(ExtractionTask.creator_id == current_user.id)
                pending_stmt = pending_stmt.where(ExtractionTask.creator_id == current_user.id)

    doc_count = await db.execute(doc_stmt)
    tmpl_count = await db.execute(tmpl_stmt)
    task_count = await db.execute(task_stmt)
    pending_tasks = await db.execute(pending_stmt)
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
    # 记录返回信息（不包含明文密钥，仅记录是否存在与长度）
    for c in configs:
        try:
            ak_len = len(c.api_key_encrypted) if c.api_key_encrypted else 0
        except Exception:
            ak_len = 0
        logger.info(f"list_llm_configs: id={c.id} name={c.name} api_key_exists={bool(c.api_key_encrypted)} api_key_len={ak_len} is_default={c.is_default} is_active={c.is_active}")

    return ResponseBase(data=[
        {
            "id": c.id, "name": c.name,
            "model_name": c.model_name, "base_url": c.base_url,
            "is_default": c.is_default, "is_active": c.is_active,
            "api_key": c.api_key_encrypted,
            "last_test_success": c.last_test_success,
            "last_test_latency_ms": c.last_test_latency_ms,
        }
        for c in configs
    ])


@router.get("/llm-options", response_model=ResponseBase[list[dict]], summary="获取可用LLM模型选项")
async def list_llm_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """普通登录用户可用，仅返回创建提取任务所需的安全字段。"""
    result = await db.execute(
        select(LLMConfig)
        .where(LLMConfig.is_active == True)
        .order_by(LLMConfig.is_default.desc(), LLMConfig.priority.desc())
    )
    configs = result.scalars().all()

    return ResponseBase(data=[
        {
            "id": c.id,
            "name": c.name,
            "model_name": c.model_name,
            "is_default": c.is_default,
            "is_active": c.is_active,
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

    try:
        logger.info(f"create_llm_config: id={config.id} name={config.name} api_key_exists={bool(config.api_key_encrypted)} api_key_len={len(config.api_key_encrypted) if config.api_key_encrypted else 0}")
    except Exception:
        logger.info(f"create_llm_config: id={config.id} name={config.name}")

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

    try:
        logger.info(f"update_llm_config: id={config.id} name={config.name} api_key_provided_in_payload={bool(payload.get('api_key'))} api_key_exists={bool(config.api_key_encrypted)} api_key_len={len(config.api_key_encrypted) if config.api_key_encrypted else 0}")
    except Exception:
        logger.info(f"update_llm_config: id={config.id} name={config.name}")

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
    error_message = None
    try:
        # 优先使用 DB 中存储的凭据（以配置中 base_url/api_key 为准）
        if config.base_url and config.api_key_encrypted:
            logger.debug(f"test_llm_config: using db stored credentials for id={config.id} base_url={config.base_url}")
            adapter = create_adapter_from_db_config(
                config.api_key_encrypted,
                config.base_url,
                model=config.model_name,
            )
        else:
            logger.debug(f"test_llm_config: falling back to default adapter for id={config.id}")
            # 回退到系统默认适配器
            adapter = get_default_adapter()
        success = await adapter.test_connection()
    except Exception as e:
        error_message = str(e)

    latency_ms = int((time.time() - start) * 1000)
    config.last_test_at = datetime.now(timezone.utc)
    config.last_test_success = success
    config.last_test_latency_ms = latency_ms
    await db.flush()

    return ResponseBase(data={"success": success, "latency_ms": latency_ms, "error_message": error_message})


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


@router.get('/roles', response_model=ResponseBase[list[dict]], summary='获取角色列表')
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    result = await db.execute(select(Role).order_by(Role.is_system.desc(), Role.name.asc()))
    roles = result.scalars().all()
    return ResponseBase(data=[
        {
            'id': r.id,
            'name': r.name,
            'display_name': r.display_name,
            'description': r.description,
            'is_system': r.is_system,
        }
        for r in roles
    ])


@router.get('/users', response_model=ResponseBase[dict], summary='管理员查询账号列表')
async def list_users(
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    query = select(User).options(selectinload(User.roles))
    if keyword:
        kw = f"%{keyword}%"
        query = query.where(
            or_(
                User.username.ilike(kw),
                User.email.ilike(kw),
                User.full_name.ilike(kw),
            )
        )

    total_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_query)).scalar() or 0

    result = await db.execute(
        query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    users = result.scalars().unique().all()
    return ResponseBase(data={
        'items': [_serialize_user(u) for u in users],
        'total': total,
        'page': page,
        'page_size': page_size,
    })


@router.post('/users', response_model=ResponseBase[dict], summary='管理员新增账号')
async def create_user(
    payload: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    # 用户名/邮箱唯一检查
    existing = await db.execute(
        select(User).where(or_(User.username == payload.username, User.email == payload.email))
    )
    if existing.scalar_one_or_none():
        from app.core.exceptions import ConflictException
        raise ConflictException('用户名或邮箱已存在')

    user = User(
        id=str(uuid.uuid4()),
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        status=payload.status,
        is_superuser=payload.is_superuser,
        created_at=datetime.now(timezone.utc),
    )

    role_ids = payload.role_ids or []
    if role_ids:
        role_result = await db.execute(select(Role).where(Role.id.in_(role_ids)))
        user.roles = role_result.scalars().all()
    else:
        # 默认分配 user 角色
        default_role = await db.execute(select(Role).where(Role.name == 'user'))
        role = default_role.scalar_one_or_none()
        if role:
            user.roles = [role]

    db.add(user)
    await db.flush()
    await db.refresh(user, attribute_names=['roles', 'created_at', 'updated_at'])
    return ResponseBase(data=_serialize_user(user))


@router.put('/users/{user_id}', response_model=ResponseBase[dict], summary='管理员更新账号')
async def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    from app.core.exceptions import NotFoundException, ConflictException

    result = await db.execute(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException('用户', user_id)

    if payload.email and payload.email != user.email:
        same_email = await db.execute(select(User).where(User.email == payload.email, User.id != user_id))
        if same_email.scalar_one_or_none():
            raise ConflictException('邮箱已被占用')
        user.email = payload.email

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    if payload.status:
        user.status = payload.status
    if payload.is_superuser is not None:
        if user.id == current_user.id and payload.is_superuser is False:
            raise ConflictException('不能取消当前登录管理员的超级管理员权限')
        user.is_superuser = payload.is_superuser

    if payload.role_ids is not None:
        if payload.role_ids:
            role_result = await db.execute(select(Role).where(Role.id.in_(payload.role_ids)))
            user.roles = role_result.scalars().all()
        else:
            user.roles = []

    await db.flush()
    await db.refresh(user, attribute_names=['roles', 'created_at', 'updated_at', 'last_login_at'])
    return ResponseBase(data=_serialize_user(user))


@router.delete('/users/{user_id}', response_model=ResponseBase[dict], summary='管理员删除账号')
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    from app.core.exceptions import NotFoundException, ConflictException

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException('用户', user_id)

    if user.id == current_user.id:
        raise ConflictException('不能删除当前登录账号')

    if user.is_superuser:
        super_count = (await db.execute(select(func.count(User.id)).where(User.is_superuser == True))).scalar() or 0
        if super_count <= 1:
            raise ConflictException('至少保留一个超级管理员账号')

    await db.delete(user)
    await db.flush()
    return ResponseBase(data={'id': user_id})
