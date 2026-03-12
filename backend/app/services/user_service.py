"""
用户服务 - 用户注册、登录、管理
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional
from app.models.user import User, Role, UserStatus
from app.schemas.user import UserCreate, UserUpdate, LoginRequest, TokenOut
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, generate_api_key
)
from app.core.exceptions import (
    NotFoundException, ConflictException,
    UnauthorizedException, ForbiddenException
)


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, data: UserCreate) -> User:
        """注册新用户"""
        # 检查用户名和邮箱是否已存在
        existing = await self.db.execute(
            select(User).where(
                or_(User.username == data.username, User.email == data.email)
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictException("用户名或邮箱已被注册")

        user = User(
            id=str(uuid.uuid4()),
            username=data.username,
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            status=UserStatus.ACTIVE,
        )
        # 分配默认角色
        default_role = await self.db.execute(
            select(Role).where(Role.name == "user")
        )
        role = default_role.scalar_one_or_none()
        if role:
            user.roles = [role]

        self.db.add(user)
        await self.db.flush()
        return user

    async def login(self, data: LoginRequest, ip: Optional[str] = None) -> TokenOut:
        """用户登录，返回 JWT 令牌对"""
        result = await self.db.execute(
            select(User).where(
                or_(User.username == data.username, User.email == data.username)
            )
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(data.password, user.hashed_password):
            raise UnauthorizedException("用户名或密码错误")

        if user.status == UserStatus.LOCKED:
            raise ForbiddenException("账号已被锁定，请联系管理员")
        if user.status == UserStatus.INACTIVE:
            raise ForbiddenException("账号未激活")

        # 更新登录信息
        user.last_login_at = datetime.now(timezone.utc)
        if ip:
            user.last_login_ip = ip

        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        from app.config import settings
        return TokenOut(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def get_by_id(self, user_id: str) -> User:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("用户", user_id)
        return user

    async def update(self, user: User, data: UserUpdate) -> User:
        """更新用户信息"""
        update_data = data.model_dump(exclude_none=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        await self.db.flush()
        return user

    async def generate_api_key(self, user: User) -> str:
        """生成 API 密钥"""
        api_key = generate_api_key()
        from app.core.security import hash_password
        # 存储哈希后的 API 密钥（实际应用中应加密存储）
        user.api_key = api_key
        from datetime import timedelta
        user.api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=365)
        await self.db.flush()
        return api_key

    async def list_users(self, page: int = 1, page_size: int = 20, keyword: Optional[str] = None):
        """分页查询用户列表"""
        query = select(User)
        if keyword:
            query = query.where(
                or_(
                    User.username.ilike(f"%{keyword}%"),
                    User.email.ilike(f"%{keyword}%"),
                    User.full_name.ilike(f"%{keyword}%"),
                )
            )
        from sqlalchemy import func
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        users = result.scalars().all()
        return users, total
