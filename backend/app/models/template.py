"""
模板相关数据模型
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Text,
    ForeignKey, JSON, Enum, Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class TemplateStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class FieldType(str, enum.Enum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    ADDRESS = "address"
    PHONE = "phone"
    EMAIL = "email"
    URL = "url"
    CUSTOM = "custom"


class TemplateCategory(Base):
    """模板分类表"""
    __tablename__ = "template_categories"

    id = Column(String(36), primary_key=True)
    name = Column(String(64), nullable=False, comment="分类名称")
    description = Column(String(255), nullable=True)
    parent_id = Column(String(36), ForeignKey("template_categories.id"), nullable=True)
    sort_order = Column(Integer, default=0, comment="排序")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    templates = relationship("Template", back_populates="category")
    children = relationship("TemplateCategory", backref="parent", remote_side=[id])


class Template(Base):
    """模板主表"""
    __tablename__ = "templates"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False, comment="模板名称")
    description = Column(Text, nullable=True, comment="模板描述")
    category_id = Column(String(36), ForeignKey("template_categories.id"), nullable=True, index=True)
    creator_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    current_version = Column(Integer, default=1, comment="当前版本号")
    status = Column(Enum(TemplateStatus), default=TemplateStatus.DRAFT, nullable=False, index=True)
    is_public = Column(Boolean, default=False, comment="是否公开")
    tags = Column(JSON, default=list, comment="标签列表")
    document_types = Column(JSON, default=list, comment="适用文档类型")
    thumbnail_url = Column(String(512), nullable=True, comment="模板缩略图")
    use_count = Column(Integer, default=0, comment="使用次数")
    # 提示词配置
    system_prompt = Column(Text, nullable=True, comment="系统提示词")
    extraction_prompt_template = Column(Text, nullable=True, comment="提取提示词模板")
    few_shot_examples = Column(JSON, default=list, comment="Few-shot示例")
    # 元数据
    meta_info = Column(JSON, default=dict, comment="附加元数据")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category = relationship("TemplateCategory", back_populates="templates")
    creator = relationship("User", back_populates="templates")
    fields = relationship("TemplateField", back_populates="template", cascade="all, delete-orphan", lazy="selectin")
    versions = relationship("TemplateVersion", back_populates="template", lazy="dynamic")
    extraction_tasks = relationship("ExtractionTask", back_populates="template", lazy="dynamic")


class TemplateField(Base):
    """模板字段定义表"""
    __tablename__ = "template_fields"

    id = Column(String(36), primary_key=True)
    template_id = Column(String(36), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False, comment="字段名称(英文key)")
    display_name = Column(String(128), nullable=False, comment="显示名称")
    field_type = Column(Enum(FieldType), default=FieldType.TEXT, nullable=False)
    description = Column(Text, nullable=True, comment="字段描述")
    required = Column(Boolean, default=False, comment="是否必填")
    default_value = Column(Text, nullable=True, comment="默认值")
    # 验证规则
    validation_rules = Column(JSON, default=dict, comment="验证规则(JSON格式)")
    # 提取配置
    extraction_hints = Column(Text, nullable=True, comment="提取提示(给LLM的额外提示)")
    region_config = Column(JSON, default=dict, comment="文档区域标注配置")
    # 关联字段
    parent_field_id = Column(String(36), ForeignKey("template_fields.id"), nullable=True)
    sort_order = Column(Integer, default=0, comment="排序")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    template = relationship("Template", back_populates="fields")
    children = relationship("TemplateField", backref="parent", remote_side=[id])


class TemplateVersion(Base):
    """模板版本历史表"""
    __tablename__ = "template_versions"

    id = Column(String(36), primary_key=True)
    template_id = Column(String(36), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, comment="版本号")
    # 版本快照（保存当时完整的模板和字段定义）
    template_snapshot = Column(JSON, nullable=False, comment="模板完整快照")
    change_description = Column(Text, nullable=True, comment="版本变更说明")
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    template = relationship("Template", back_populates="versions")
