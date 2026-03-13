"""
系统配置相关数据模型 (LLM配置、系统设置、任务配置)
"""
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text, JSON, Float
from sqlalchemy.sql import func
import enum
from app.database import Base


class LLMConfig(Base):
    """LLM配置表 - 支持多模型、多提供商配置"""
    __tablename__ = "llm_configs"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False, comment="配置名称")
    model_name = Column(String(128), nullable=False, comment="模型名称")
    api_key_encrypted = Column(Text, nullable=True, comment="加密的API密钥")
    base_url = Column(String(512), nullable=True, comment="API基础URL")
    # 模型参数
    temperature = Column(Float, default=0.1, comment="温度参数")
    max_tokens = Column(Integer, default=4096, comment="最大Token数")
    top_p = Column(Float, default=1.0)
    extra_params = Column(JSON, default=dict, comment="其他模型参数")
    # 状态与权重
    is_active = Column(Boolean, default=True, comment="是否启用")
    is_default = Column(Boolean, default=False, comment="是否为默认配置")
    weight = Column(Integer, default=1, comment="负载均衡权重")
    priority = Column(Integer, default=0, comment="优先级(数字越大越优先)")
    # 限额
    daily_token_limit = Column(Integer, nullable=True, comment="每日Token限额")
    monthly_token_limit = Column(Integer, nullable=True, comment="每月Token限额")
    # 测试状态
    last_test_at = Column(DateTime(timezone=True), nullable=True, comment="最后测试时间")
    last_test_success = Column(Boolean, nullable=True, comment="最后测试是否成功")
    last_test_latency_ms = Column(Integer, nullable=True, comment="最后测试延迟(ms)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SystemConfig(Base):
    """系统配置表 - 键值对形式存储"""
    __tablename__ = "system_configs"

    id = Column(String(36), primary_key=True)
    category = Column(String(64), nullable=False, index=True, comment="配置分类")
    key = Column(String(128), nullable=False, unique=True, comment="配置键")
    value = Column(Text, nullable=True, comment="配置值")
    default_value = Column(Text, nullable=True, comment="默认值")
    description = Column(Text, nullable=True, comment="配置说明")
    data_type = Column(String(32), default="string", comment="数据类型(string/int/float/bool/json)")
    is_encrypted = Column(Boolean, default=False, comment="是否加密存储")
    is_editable = Column(Boolean, default=True, comment="是否可通过界面编辑")
    updated_by = Column(String(36), nullable=True, comment="最后修改人ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobConfig(Base):
    """任务配置表"""
    __tablename__ = "job_configs"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False, unique=True, comment="任务配置名称")
    description = Column(Text, nullable=True)
    # 并发与重试
    max_concurrent_tasks = Column(Integer, default=5, comment="最大并发任务数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")
    retry_delay_seconds = Column(Integer, default=60, comment="重试延迟(秒)")
    task_timeout_seconds = Column(Integer, default=300, comment="任务超时(秒)")
    # 队列配置
    queue_name = Column(String(64), default="default", comment="Celery队列名称")
    priority = Column(Integer, default=5, comment="优先级(1-10)")
    # 通知配置
    notify_on_completion = Column(Boolean, default=False, comment="完成时通知")
    notify_on_failure = Column(Boolean, default=True, comment="失败时通知")
    notify_webhook_url = Column(String(512), nullable=True, comment="通知Webhook URL")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
