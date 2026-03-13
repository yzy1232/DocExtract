"""
模板相关 Pydantic Schema
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.template import TemplateStatus, FieldType


class TemplateFieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="字段名(英文key)")
    display_name: str = Field(min_length=1, max_length=128)
    field_type: FieldType = FieldType.TEXT
    description: Optional[str] = None
    required: bool = False
    default_value: Optional[str] = None
    validation_rules: Dict[str, Any] = Field(default_factory=dict)
    extraction_hints: Optional[str] = None
    region_config: Dict[str, Any] = Field(default_factory=dict)
    parent_field_id: Optional[str] = None
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        import re
        # 允许中文、英文字母或下划线开头，后续字符允许中文/英文字母/数字/下划线
        pattern = "^[\u4e00-\u9fff_a-zA-Z][\u4e00-\u9fff_a-zA-Z0-9_]*$"
        if not re.match(pattern, v):
            raise ValueError("字段名必须以中文、字母或下划线开头，只能包含中文、字母、数字和下划线")
        return v


class TemplateFieldUpdate(BaseModel):
    display_name: Optional[str] = None
    field_type: Optional[FieldType] = None
    description: Optional[str] = None
    required: Optional[bool] = None
    default_value: Optional[str] = None
    validation_rules: Optional[Dict[str, Any]] = None
    extraction_hints: Optional[str] = None
    region_config: Optional[Dict[str, Any]] = None
    sort_order: Optional[int] = None


class TemplateFieldOut(BaseModel):
    id: str
    name: str
    display_name: str
    field_type: FieldType
    description: Optional[str] = None
    required: bool
    default_value: Optional[str] = None
    validation_rules: Dict[str, Any]
    extraction_hints: Optional[str] = None
    region_config: Dict[str, Any]
    parent_field_id: Optional[str] = None
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="模板名称")
    description: Optional[str] = None
    category_id: Optional[str] = None
    is_public: bool = False
    tags: List[str] = Field(default_factory=list)
    document_types: List[str] = Field(default_factory=list)
    fields: List[TemplateFieldCreate] = Field(default_factory=list)
    system_prompt: Optional[str] = None
    extraction_prompt_template: Optional[str] = None
    few_shot_examples: List[Dict[str, Any]] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = None
    category_id: Optional[str] = None
    status: Optional[TemplateStatus] = None
    is_public: Optional[bool] = None
    tags: Optional[List[str]] = None
    document_types: Optional[List[str]] = None
    system_prompt: Optional[str] = None
    extraction_prompt_template: Optional[str] = None
    few_shot_examples: Optional[List[Dict[str, Any]]] = None
    change_description: Optional[str] = Field(default=None, description="版本变更说明")
    # 允许在更新模板时同时替换字段定义（将替换为提交的字段列表）
    fields: Optional[List[TemplateFieldCreate]] = None


class TemplateOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category_id: Optional[str] = None
    creator_id: Optional[str] = None
    current_version: int
    status: TemplateStatus
    is_public: bool
    tags: List[str]
    document_types: List[str]
    thumbnail_url: Optional[str] = None
    use_count: int
    fields: List[TemplateFieldOut] = []
    system_prompt: Optional[str] = None
    extraction_prompt_template: Optional[str] = None
    few_shot_examples: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateListOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category_id: Optional[str] = None
    status: TemplateStatus
    is_public: bool
    tags: List[str]
    use_count: int
    field_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: Optional[str] = None
    parent_id: Optional[str] = None
    sort_order: int = 0


class TemplateCategoryOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[str] = None
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}
