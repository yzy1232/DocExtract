"""
初始化系统默认数据：角色、权限、默认管理员
在应用首次启动时运行（可通过环境变量控制）
"""
from typing import Optional
import uuid
from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.database import AsyncSessionLocal
from app.models.user import User, Role, UserStatus
from app.models.system import SystemConfig
from app.config import settings
from app.core.security import hash_password

logger = logging.getLogger("app")
BOOTSTRAP_FLAG_KEY = "system_bootstrap_done"


async def ensure_default_roles_and_admin() -> None:
    if not settings.AUTO_CREATE_ADMIN:
        return

    async with AsyncSessionLocal() as session:
        # 使用 MySQL 的 GET_LOCK 进行进程间互斥，避免多个 worker/重载进程同时进行初始化
        lock_name = "init_defaults_lock"
        try:
            res = await session.execute(text("SELECT GET_LOCK(:name, :timeout)"), {"name": lock_name, "timeout": 10})
            got = res.scalar()
        except Exception:
            got = None

        if not got:
            logger.info("未获得初始化锁（可能另一个实例正在初始化），跳过创建默认角色与管理员")
            return
        # 创建默认角色（admin, user） — 使用 try/except 防止并发时的唯一约束冲突
        try:
            result = await session.execute(select(Role).where(Role.name == 'admin'))
            admin_role = result.scalar_one_or_none()
            if not admin_role:
                admin_role = Role(
                    id=str(uuid.uuid4()),
                    name='admin',
                    display_name='Administrator',
                    description='系统管理员，拥有全部权限',
                    is_system=True,
                )
                session.add(admin_role)

            result = await session.execute(select(Role).where(Role.name == 'user'))
            user_role = result.scalar_one_or_none()
            if not user_role:
                user_role = Role(
                    id=str(uuid.uuid4()),
                    name='user',
                    display_name='User',
                    description='普通用户角色',
                    is_system=True,
                )
                session.add(user_role)

            await session.flush()
            await session.commit()
        except IntegrityError:
            # 发生唯一约束冲突（可能并发），回滚并重新读取已有角色
            await session.rollback()
            result = await session.execute(select(Role).where(Role.name == 'admin'))
            admin_role = result.scalar_one_or_none()
            result = await session.execute(select(Role).where(Role.name == 'user'))
            user_role = result.scalar_one_or_none()

        # 如果不存在超级管理员，则创建
        result = await session.execute(select(User).where(User.is_superuser == True))
        superuser = result.scalar_one_or_none()
        if not superuser:
            username = settings.DEFAULT_ADMIN_USERNAME
            password = settings.DEFAULT_ADMIN_PASSWORD
            email = settings.DEFAULT_ADMIN_EMAIL

            # 避免与现有同名用户冲突
            result = await session.execute(select(User).where(User.username == username))
            existing = result.scalar_one_or_none()
            if existing:
                # 将现有用户提升为超级管理员
                existing.is_superuser = True
                existing.status = UserStatus.ACTIVE
                await session.commit()
                logger.info(f"已将用户 {existing.username} 提升为超级管理员")
                return
            try:
                hashed = hash_password(password)

                admin_user = User(
                    id=str(uuid.uuid4()),
                    username=username,
                    email=email,
                    hashed_password=hashed,
                    full_name='Administrator',
                    status=UserStatus.ACTIVE,
                    is_superuser=True,
                    created_at=datetime.now(timezone.utc),
                )
                # 赋予 admin 角色
                admin_user.roles = [admin_role]
                session.add(admin_user)
                await session.flush()
                await session.commit()
                logger.info(f"创建默认管理员: {username}")
            except IntegrityError:
                # 唯一约束冲突（可能另一个进程/线程已创建该用户），回滚并尝试提升已有用户为超级管理员
                await session.rollback()
                result = await session.execute(select(User).where(User.username == username))
                existing = result.scalar_one_or_none()
                if existing:
                    existing.is_superuser = True
                    existing.status = UserStatus.ACTIVE
                    await session.commit()
                    logger.info(f"已将现有用户 {username} 提升为超级管理员（冲突处理）")
                else:
                    logger.warning("创建管理员时发生唯一约束冲突，但未找到现有用户")
            except Exception as e:
                await session.rollback()
                logger.warning(f"默认数据初始化失败: {e}")
                return
            finally:
            # 释放锁
                try:
                    await session.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
                except Exception:
                    pass


async def ensure_default_llm_system_config() -> None:
    """确保 SystemConfig 中存在 default_llm_config_id 键（用于回退与 UI 读取）。
    在首次启动时写入一条空值记录，避免后续读取出现 404。
    """
    if not settings.AUTO_CREATE_ADMIN:
        # 与其他默认数据的控制保持一致，使用相同环境开关
        return

    async with AsyncSessionLocal() as session:
        # 使用数据库锁避免并发创建冲突 / 死锁
        lock_name = "init_defaults_lock"
        try:
            res = await session.execute(text("SELECT GET_LOCK(:name, :timeout)"), {"name": lock_name, "timeout": 10})
            got = res.scalar()
        except Exception:
            got = None

        if not got:
            logger.info("未获得初始化锁（可能另一个实例正在初始化），跳过创建 default_llm_config_id")
            return

        try:
            result = await session.execute(select(SystemConfig).where(SystemConfig.key == 'default_llm_config_id'))
            sc = result.scalar_one_or_none()
            if not sc:
                new_sc = SystemConfig(
                    id=str(uuid.uuid4()),
                    category='system',
                    key='default_llm_config_id',
                    value='',
                    default_value=None,
                    description='系统默认LLM配置ID（自动创建）',
                    data_type='string',
                    is_editable=True,
                    is_encrypted=False,
                    updated_by=None,
                )
                session.add(new_sc)
                await session.flush()
                await session.commit()
                logger.info('已创建默认 SystemConfig: default_llm_config_id')
        except IntegrityError:
            await session.rollback()
        except Exception as e:
            await session.rollback()
            logger.warning(f"创建 default_llm_config_id 失败: {e}")
        finally:
            try:
                await session.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
            except Exception:
                pass


async def is_system_bootstrap_completed() -> bool:
    """检查系统是否已经完成首次初始化。"""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.key == BOOTSTRAP_FLAG_KEY)
            )
            cfg = result.scalar_one_or_none()
            return bool(cfg and str(cfg.value) == "1")
        except Exception:
            # 表还不存在或数据库尚未完成初始化时，视为未初始化
            return False


async def mark_system_bootstrap_completed() -> None:
    """写入首次初始化完成标记。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SystemConfig).where(SystemConfig.key == BOOTSTRAP_FLAG_KEY))
        cfg = result.scalar_one_or_none()
        if cfg:
            cfg.value = "1"
            cfg.description = "系统首次初始化是否完成"
            cfg.data_type = "bool"
        else:
            cfg = SystemConfig(
                id=str(uuid.uuid4()),
                category="system",
                key=BOOTSTRAP_FLAG_KEY,
                value="1",
                default_value="0",
                description="系统首次初始化是否完成",
                data_type="bool",
                is_editable=False,
                is_encrypted=False,
                updated_by=None,
            )
            session.add(cfg)
        await session.commit()
