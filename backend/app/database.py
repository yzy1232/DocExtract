"""
数据库连接模块 - 异步 SQLAlchemy 配置
"""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text
from typing import AsyncGenerator
import logging
from app.config import settings


# 创建异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,          # 连接前检测连接活性
    pool_recycle=3600,           # 1小时回收连接
    echo=settings.DEBUG,
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


logger = logging.getLogger("app")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入 - 获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except asyncio.CancelledError:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """创建所有数据库表（开发/测试环境使用，生产使用 Alembic）"""
    lock_name = "create_tables_lock"
    async with engine.connect() as conn:
        got_lock = False
        try:
            if conn.dialect.name == "mysql":
                res = await conn.execute(
                    text("SELECT GET_LOCK(:name, :timeout)"),
                    {"name": lock_name, "timeout": 10},
                )
                got_lock = bool(res.scalar())
                if not got_lock:
                    logger.info("未获得建表锁，跳过 create_tables")
                    return
            else:
                # 非 MySQL 环境不需要 GET_LOCK
                got_lock = True

            # 批量 checkfirst 建表，避免并发下按表逐个创建触发竞争
            await conn.run_sync(lambda c: Base.metadata.create_all(bind=c, checkfirst=True))
            await conn.commit()
        finally:
            if conn.dialect.name == "mysql" and got_lock:
                try:
                    await conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
                    await conn.commit()
                except Exception:
                    pass


async def drop_tables():
    """删除所有数据库表（仅测试环境使用）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
