"""
FastAPI 应用主入口 - API 网关层
"""
import logging
import logging.config
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.database import create_tables
from app.api.v1 import api_router
from app.websocket.handlers import ws_router
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
)
from app.core.middleware import RequestTracingMiddleware, SecurityHeadersMiddleware
from app.core.cache import get_redis, close_redis
from app.core.storage import ensure_buckets

# ========================
# 日志配置
# ========================
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")


# ========================
# 应用生命周期
# ========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭钩子"""
    # 启动
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    try:
        await create_tables()
        logger.info("数据库表初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化失败（可忽略，如使用 Alembic）: {e}")

    try:
        redis = await get_redis()
        await redis.ping()
        logger.info("Redis 连接成功")
    except Exception as e:
        logger.warning(f"Redis 连接失败: {e}")

    try:
        ensure_buckets()
        logger.info("对象存储桶初始化完成")
    except Exception as e:
        logger.warning(f"对象存储初始化失败: {e}")

    # 尝试创建系统默认数据（角色、默认管理员）
    try:
        from app.core.init_defaults import ensure_default_roles_and_admin

        await ensure_default_roles_and_admin()
        logger.info("默认角色与管理员初始化完成")
    except Exception as e:
        logger.warning(f"默认数据初始化失败: {e}")

    try:
        from app.core.init_defaults import ensure_default_llm_system_config

        await ensure_default_llm_system_config()
        logger.info("默认 LLM 系统配置初始化完成")
    except Exception as e:
        logger.warning(f"默认数据初始化失败: {e}")

    yield  # 应用运行期间

    # 关闭
    await close_redis()
    logger.info("应用已关闭")


# ========================
# FastAPI 应用实例
# ========================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 基于大语言模型的文档理解与模板提取系统

### 主要功能
- **模板管理**: 创建和管理提取模板，定义字段结构
- **文档上传**: 支持 PDF/DOCX/XLSX/图片等多种格式
- **智能提取**: 基于 LLM 从文档中提取结构化信息
- **结果管理**: 查看、验证、导出提取结果

### 认证方式
使用 JWT Bearer Token，通过 `/api/v1/auth/login` 获取。
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ========================
# 中间件注册（顺序很重要）
# ========================
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTracingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================
# 异常处理器
# ========================
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ========================
# 路由注册
# ========================
app.include_router(api_router)
app.include_router(ws_router)


@app.get("/", include_in_schema=False)
async def root():
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}
