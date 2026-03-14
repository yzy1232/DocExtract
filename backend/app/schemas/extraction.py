"""
文档和提取相关 Pydantic Schema
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.document import DocumentStatus, DocumentFormat
from app.models.extraction import TaskStatus, TaskPriority


# ========================
# 文档 Schema
# ========================

class DocumentOut(BaseModel):
    id: str
    name: str
    display_name: Optional[str] = None
    format: DocumentFormat
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    status: DocumentStatus
    page_count: Optional[int] = None
    language: Optional[str] = None
    has_ocr: bool
    parsed_text_preview: Optional[str] = None
    tags: List[str]
    owner_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    id: str
    name: str
    display_name: Optional[str] = None
    format: DocumentFormat
    file_size: Optional[int] = None
    status: DocumentStatus
    page_count: Optional[int] = None
    tags: List[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=512)
    tags: Optional[List[str]] = None


class DocumentUploadInit(BaseModel):
    """分片上传初始化"""
    filename: str
    file_size: int
    mime_type: str
    chunk_size: int = Field(default=5 * 1024 * 1024, description="分片大小(字节)")


class UploadSession(BaseModel):
    """上传会话信息"""
    upload_id: str
    document_id: str
    presigned_urls: List[str]
    chunk_count: int


# ========================
# 提取任务 Schema
# ========================

class ExtractionCreate(BaseModel):
    document_id: str
    template_id: str
    priority: TaskPriority = TaskPriority.NORMAL
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    extra_config: Dict[str, Any] = Field(default_factory=dict)


class BatchExtractionCreate(BaseModel):
    document_ids: List[str] = Field(min_length=1, max_length=50)
    template_id: str
    priority: TaskPriority = TaskPriority.NORMAL
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None


class ExtractionFieldOut(BaseModel):
    id: str
    field_name: str
    raw_value: Optional[str] = None
    normalized_value: Optional[str] = None
    value_type: Optional[str] = None
    confidence: Optional[float] = None
    is_valid: Optional[bool] = None
    validation_error: Optional[str] = None
    source_page: Optional[int] = None
    source_text: Optional[str] = None

    model_config = {"from_attributes": True}


class ExtractionResultOut(BaseModel):
    id: str
    task_id: str
    structured_result: Dict[str, Any]
    overall_confidence: Optional[float] = None
    validation_status: str
    validation_notes: Optional[str] = None
    export_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExtractionTaskOut(BaseModel):
    id: str
    document_id: str
    template_id: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int
    error_message: Optional[str] = None
    token_used: Optional[int] = None
    processing_time_ms: Optional[int] = None
    progress: float
    progress_message: Optional[str] = None
    results: Optional[ExtractionResultOut] = None
    field_results: List[ExtractionFieldOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExtractionTaskListOut(BaseModel):
    id: str
    document_id: str
    template_id: Optional[str] = None
    document_name: Optional[str] = None
    template_name: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    progress: float
    created_at: datetime

    model_config = {"from_attributes": True}


class ResultValidationUpdate(BaseModel):
    validation_status: str = Field(pattern="^(passed|failed|manual)$")
    validation_notes: Optional[str] = None


class ExportRequest(BaseModel):
    task_ids: List[str] = Field(min_length=1, max_length=100)
    format: str = Field(default="xlsx", pattern="^(xlsx|csv|json|pdf)$")
    include_confidence: bool = False
