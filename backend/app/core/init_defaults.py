"""
初始化系统默认数据：角色、权限、默认管理员
在应用首次启动时运行（可通过环境变量控制）
"""
from typing import Optional
import uuid
from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import AsyncSessionLocal
from app.models.user import User, Role, UserStatus
from app.config import settings
from app.core.security import hash_password

logger = logging.getLogger("app")


async def ensure_default_roles_and_admin() -> None:
    if not settings.AUTO_CREATE_ADMIN:
        return

    async with AsyncSessionLocal() as session:
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
