"""
提取任务和结果相关数据模型
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Text,
    ForeignKey, JSON, Enum, Float, BigInteger
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ExtractionTask(Base):
    """提取任务主表"""
    __tablename__ = "extraction_tasks"

    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id = Column(String(36), ForeignKey("templates.id", ondelete="SET NULL"), nullable=True, index=True)
    creator_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # 任务配置
    celery_task_id = Column(String(255), nullable=True, index=True, comment="Celery任务ID")
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True)
    priority = Column(Enum(TaskPriority), default=TaskPriority.NORMAL, nullable=False)
    # LLM配置
    llm_provider = Column(String(32), nullable=True, comment="使用的LLM提供商")
    llm_model = Column(String(64), nullable=True, comment="使用的LLM模型")
    llm_config_snapshot = Column(JSON, default=dict, comment="LLM配置快照")
    # 执行信息
    started_at = Column(DateTime(timezone=True), nullable=True, comment="开始时间")
    completed_at = Column(DateTime(timezone=True), nullable=True, comment="完成时间")
    retry_count = Column(Integer, default=0, comment="重试次数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")
    error_message = Column(Text, nullable=True, comment="错误信息")
    # 统计
    token_used = Column(Integer, nullable=True, comment="消耗Token数")
    processing_time_ms = Column(Integer, nullable=True, comment="处理时间(毫秒)")
    # 进度
    progress = Column(Float, default=0.0, comment="进度(0-100)")
    progress_message = Column(String(255), nullable=True, comment="进度消息")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    document = relationship("Document", back_populates="extraction_tasks")
    template = relationship("Template", back_populates="extraction_tasks")
    results = relationship("ExtractionResult", back_populates="task", cascade="all, delete-orphan", uselist=False)
    field_results = relationship("ExtractionField", back_populates="task", cascade="all, delete-orphan", lazy="selectin")
    logs = relationship("ExtractionLog", back_populates="task", cascade="all, delete-orphan", lazy="dynamic")


class ExtractionResult(Base):
    """提取结果汇总表"""
    __tablename__ = "extraction_results"

    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("extraction_tasks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    # 整体结果
    raw_result = Column(JSON, default=dict, comment="LLM原始返回结果")
    structured_result = Column(JSON, default=dict, comment="结构化提取结果(字段名:值)")
    # 质量评估
    overall_confidence = Column(Float, nullable=True, comment="整体置信度(0-1)")
    validation_status = Column(String(32), default="pending", comment="验证状态(pending/passed/failed/manual)")
    validation_notes = Column(Text, nullable=True, comment="验证备注")
    validated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    # 导出
    export_url = Column(String(1024), nullable=True, comment="导出文件URL")
    export_format = Column(String(16), nullable=True, comment="导出格式")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    task = relationship("ExtractionTask", back_populates="results")


class ExtractionField(Base):
    """字段级提取结果表"""
    __tablename__ = "extraction_fields"

    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("extraction_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    field_id = Column(String(36), ForeignKey("template_fields.id", ondelete="SET NULL"), nullable=True)
    field_name = Column(String(64), nullable=False, comment="字段名称")
    # 提取结果
    raw_value = Column(Text, nullable=True, comment="原始提取值")
    normalized_value = Column(Text, nullable=True, comment="标准化后的值")
    value_type = Column(String(32), nullable=True, comment="值类型")
    # 质量
    confidence = Column(Float, nullable=True, comment="置信度(0-1)")
    is_valid = Column(Boolean, nullable=True, comment="验证是否通过")
    validation_error = Column(Text, nullable=True, comment="验证错误信息")
    # 来源追踪
    source_page = Column(Integer, nullable=True, comment="来源页码")
    source_text = Column(Text, nullable=True, comment="来源文本片段")
    extraction_method = Column(String(32), nullable=True, comment="提取方式(llm/regex/rule)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("ExtractionTask", back_populates="field_results")


class ExtractionLog(Base):
    """提取过程日志表"""
    __tablename__ = "extraction_logs"

    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("extraction_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String(16), default="info", comment="日志级别")
    stage = Column(String(64), nullable=True, comment="处理阶段")
    message = Column(Text, nullable=False, comment="日志内容")
    extra_data = Column(JSON, default=dict, comment="附加数据")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    task = relationship("ExtractionTask", back_populates="logs")
