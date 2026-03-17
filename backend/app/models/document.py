"""
文档相关数据模型
"""
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Text,
    ForeignKey, JSON, Enum, BigInteger, Float
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class DocumentStatus(str, enum.Enum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    DELETED = "deleted"


class DocumentFormat(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    TXT = "txt"
    IMAGE = "image"
    UNKNOWN = "unknown"


class Document(Base):
    """文档主表"""
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(512), nullable=False, comment="原始文件名")
    display_name = Column(String(512), nullable=True, comment="显示名称")
    format = Column(Enum(DocumentFormat), nullable=False, index=True, comment="文档格式")
    mime_type = Column(String(128), nullable=True, comment="MIME类型")
    file_size = Column(BigInteger, nullable=True, comment="文件大小(字节)")
    file_hash = Column(String(64), nullable=True, index=True, comment="文件SHA256哈希")
    storage_path = Column(String(1024), nullable=True, comment="存储路径(对象存储key)")
    storage_bucket = Column(String(64), nullable=True, comment="存储桶名称")
    status = Column(Enum(DocumentStatus), default=DocumentStatus.UPLOADING, nullable=False, index=True)
    page_count = Column(Integer, nullable=True, comment="页数")
    language = Column(String(16), nullable=True, comment="文档语言")
    encoding = Column(String(32), nullable=True, comment="文本编码")
    has_ocr = Column(Boolean, default=False, comment="是否经过OCR")
    # 解析结果摘要
    parsed_text_preview = Column(Text, nullable=True, comment="解析文本预览(前500字)")
    parsing_error = Column(Text, nullable=True, comment="解析错误信息")
    # 上传信息
    upload_ip = Column(String(45), nullable=True, comment="上传者IP")
    tags = Column(JSON, default=list, comment="标签")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, comment="软删除时间")

    owner = relationship("User", back_populates="documents")
    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan", lazy="dynamic")
    segments = relationship("DocumentSegment", back_populates="document", cascade="all, delete-orphan", lazy="dynamic")
    metadata_records = relationship("DocumentMetadata", back_populates="document", cascade="all, delete-orphan", lazy="selectin")
    extraction_tasks = relationship("ExtractionTask", back_populates="document", lazy="dynamic")


class DocumentPage(Base):
    """文档页面表"""
    __tablename__ = "document_pages"

    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False, comment="页码(从1开始)")
    # 页面内容
    raw_text = Column(
        Text().with_variant(mysql.LONGTEXT(), "mysql"),
        nullable=True,
        comment="原始文本内容",
    )
    structured_content = Column(JSON, default=dict, comment="结构化内容(段落/表格/图片)")
    # 页面图像
    image_storage_path = Column(String(1024), nullable=True, comment="页面图像存储路径")
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    # 质量评估
    text_confidence = Column(Float, nullable=True, comment="文本识别置信度(OCR)")
    is_scanned = Column(Boolean, default=False, comment="是否为扫描页")
    has_table = Column(Boolean, default=False, comment="是否含表格")
    has_image = Column(Boolean, default=False, comment="是否含图片")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="pages")


class DocumentSegment(Base):
    """文档分段表 - 用于长文档分段处理"""
    __tablename__ = "document_segments"

    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False, comment="分段序号")
    content = Column(Text, nullable=False, comment="分段文本内容")
    token_count = Column(Integer, nullable=True, comment="Token数量(估算)")
    start_page = Column(Integer, nullable=True, comment="起始页码")
    end_page = Column(Integer, nullable=True, comment="结束页码")
    embedding = Column(JSON, nullable=True, comment="向量嵌入(可选)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="segments")


class DocumentMetadata(Base):
    """文档元数据表"""
    __tablename__ = "document_metadata"

    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(64), nullable=False, comment="元数据键")
    value = Column(Text, nullable=True, comment="元数据值")
    data_type = Column(String(32), default="string", comment="数据类型")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="metadata_records")
