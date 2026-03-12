"""
认证相关 API - 登录、注册、刷新令牌
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.user import LoginRequest, UserCreate, TokenOut, UserOut
from app.schemas.common import ResponseBase
from app.services.user_service import UserService
from app.core.auth import get_current_user
from app.models.user import User
from app.core.security import decode_token, create_access_token
from app.core.exceptions import UnauthorizedException

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=ResponseBase[UserOut], summary="用户注册")
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    svc = UserService(db)
    user = await svc.register(data)
    return ResponseBase(data=UserOut.model_validate(user))


@router.post("/login", response_model=ResponseBase[TokenOut], summary="用户登录")
async def login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = UserService(db)
    client_ip = request.client.host if request.client else None
    token = await svc.login(data, ip=client_ip)
    return ResponseBase(data=token)


@router.post("/refresh", response_model=ResponseBase[TokenOut], summary="刷新访问令牌")
async def refresh_token(refresh_token: str, db: AsyncSession = Depends(get_db)):
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise UnauthorizedException("无效的刷新令牌")

    user_id = payload.get("sub")
    new_access_token = create_access_token(user_id)

    from app.config import settings
    return ResponseBase(data=TokenOut(
        access_token=new_access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    ))


@router.get("/me", response_model=ResponseBase[UserOut], summary="获取当前用户信息")
async def get_me(current_user: User = Depends(get_current_user)):
    return ResponseBase(data=UserOut.model_validate(current_user))
