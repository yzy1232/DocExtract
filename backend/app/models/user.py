"""
用户、角色、权限相关数据模型
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Text,
    ForeignKey, Table, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


# 用户-角色 多对多关联表
user_role_association = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

# 角色-权限 多对多关联表
role_permission_association = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(36), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, comment="用户ID (UUID)")
    username = Column(String(64), unique=True, nullable=False, index=True, comment="用户名")
    email = Column(String(255), unique=True, nullable=False, index=True, comment="邮箱")
    hashed_password = Column(String(255), nullable=False, comment="哈希密码")
    full_name = Column(String(128), nullable=True, comment="姓名")
    avatar_url = Column(String(512), nullable=True, comment="头像URL")
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE, nullable=False, comment="状态")
    is_superuser = Column(Boolean, default=False, nullable=False, comment="是否超级管理员")
    last_login_at = Column(DateTime(timezone=True), nullable=True, comment="最后登录时间")
    last_login_ip = Column(String(45), nullable=True, comment="最后登录IP")
    api_key = Column(String(64), unique=True, nullable=True, index=True, comment="API密钥")
    api_key_expires_at = Column(DateTime(timezone=True), nullable=True, comment="API密钥过期时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    roles = relationship("Role", secondary=user_role_association, back_populates="users", lazy="selectin")
    documents = relationship("Document", back_populates="owner", lazy="dynamic")
    templates = relationship("Template", back_populates="creator", lazy="dynamic")
    audit_logs = relationship("AuditLog", back_populates="user", lazy="dynamic")


class Role(Base):
    """角色表"""
    __tablename__ = "roles"

    id = Column(String(36), primary_key=True)
    name = Column(String(64), unique=True, nullable=False, comment="角色名称")
    display_name = Column(String(128), nullable=False, comment="显示名称")
    description = Column(Text, nullable=True, comment="角色描述")
    is_system = Column(Boolean, default=False, comment="是否系统内置角色")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users = relationship("User", secondary=user_role_association, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permission_association, back_populates="roles", lazy="selectin")


class Permission(Base):
    """权限表"""
    __tablename__ = "permissions"

    id = Column(String(36), primary_key=True)
    resource = Column(String(64), nullable=False, comment="资源类型(template/document/extraction等)")
    action = Column(String(32), nullable=False, comment="操作类型(create/read/update/delete)")
    description = Column(String(255), nullable=True, comment="权限描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    roles = relationship("Role", secondary=role_permission_association, back_populates="permissions")


class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(64), nullable=False, comment="操作类型")
    resource_type = Column(String(64), nullable=True, comment="资源类型")
    resource_id = Column(String(36), nullable=True, comment="资源ID")
    ip_address = Column(String(45), nullable=True, comment="IP地址")
    user_agent = Column(String(512), nullable=True, comment="User-Agent")
    request_data = Column(Text, nullable=True, comment="请求数据(JSON)")
    response_code = Column(Integer, nullable=True, comment="响应状态码")
    error_message = Column(Text, nullable=True, comment="错误信息")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="audit_logs")
