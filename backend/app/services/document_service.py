"""
文档服务 - 文档上传、解析、管理
"""
import uuid
import os
import logging
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.models.document import Document, DocumentPage, DocumentMetadata, DocumentStatus, DocumentFormat
from app.schemas.extraction import DocumentUpdate
from app.core.storage import storage
from app.core.exceptions import (
    NotFoundException, FileTooLargeException, UnsupportedFileTypeException, StorageException
)
from app.processors.factory import get_processor, get_document_format, suggest_tags
from app.processors.mime_resolver import normalize_mime_type
from app.config import settings


logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upload(
        self,
        file_content: bytes,
        filename: str,
        mime_type: str,
        owner_id: str,
        tags: Optional[List[str]] = None,
        upload_ip: Optional[str] = None,
    ) -> Document:
        """上传并异步触发解析流程"""
        normalized_mime_type = normalize_mime_type(mime_type, filename)

        # 安全校验
        if len(file_content) > settings.MAX_UPLOAD_SIZE:
            raise FileTooLargeException(settings.MAX_UPLOAD_SIZE // (1024 * 1024))
        if normalized_mime_type not in settings.ALLOWED_MIME_TYPES:
            raise UnsupportedFileTypeException(normalized_mime_type)

        file_hash = storage.calculate_sha256(file_content)
        doc_format = get_document_format(normalized_mime_type, filename=filename)
        doc_id = str(uuid.uuid4())
        base_tags = tags or []
        dynamic_tags = suggest_tags(normalized_mime_type, filename=filename)
        merged_tags = sorted(set(base_tags + dynamic_tags))

        # 上传到对象存储
        try:
            storage_key = storage.build_document_key(doc_id, filename)
            import io
            storage.upload_file(
                bucket=settings.STORAGE_BUCKET_DOCUMENTS,
                object_name=storage_key,
                data=io.BytesIO(file_content),
                length=len(file_content),
                content_type=normalized_mime_type,
                metadata={"original_filename": filename},
            )
        except Exception as e:
            logger.exception("上传对象存储失败: filename=%s mime_type=%s owner_id=%s", filename, normalized_mime_type, owner_id)
            raise StorageException(f"文件上传到存储服务失败: {str(e)}")

        # 创建文档记录
        document = Document(
            id=doc_id,
            owner_id=owner_id,
            name=filename,
            display_name=filename,
            format=DocumentFormat(doc_format),
            mime_type=normalized_mime_type,
            file_size=len(file_content),
            file_hash=file_hash,
            storage_path=storage_key,
            storage_bucket=settings.STORAGE_BUCKET_DOCUMENTS,
            status=DocumentStatus.UPLOADED,
            tags=merged_tags,
            upload_ip=upload_ip,
        )
        self.db.add(document)
        await self.db.flush()
        # 立即回填 server_default 字段，避免响应序列化时触发异步懒加载
        await self.db.refresh(document)

        # 触发异步解析任务
        try:
            from app.tasks.document_tasks import parse_document_task
            parse_document_task.delay(doc_id)
        except Exception:
            logger.warning("触发文档解析任务失败，已忽略: document_id=%s", doc_id, exc_info=True)
            # 任务队列不可用时不影响主流程
            pass

        return document

    async def parse_document(self, document_id: str) -> Document:
        """同步解析文档（供任务队列调用）"""
        from sqlalchemy.orm import selectinload
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise NotFoundException("文档", document_id)

        document.status = DocumentStatus.PROCESSING
        await self.db.flush()

        try:
            # 从存储服务下载文件内容
            file_content = storage.download_file(
                document.storage_bucket, document.storage_path
            )

            document.mime_type = normalize_mime_type(document.mime_type, document.name)
            document.format = DocumentFormat(get_document_format(document.mime_type, filename=document.name))
            document.tags = sorted(set((document.tags or []) + suggest_tags(document.mime_type, filename=document.name)))

            # 获取处理器
            processor = get_processor(document.mime_type)
            if not processor:
                raise ValueError(f"不支持的文件类型: {document.mime_type}")

            # 解析文档
            parse_result = await processor.parse(file_content, document.name)

            # 保存解析结果
            document.page_count = parse_result.page_count
            document.language = parse_result.language
            document.encoding = parse_result.encoding
            document.has_ocr = parse_result.has_ocr
            document.parsed_text_preview = parse_result.full_text[:500] if parse_result.full_text else None
            document.status = DocumentStatus.PROCESSED

            # 保存页面数据
            for page in parse_result.pages:
                doc_page = DocumentPage(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    page_number=page.page_number,
                    raw_text=page.raw_text,
                    structured_content={"tables": page.tables, "images": page.images},
                    has_table=page.has_table,
                    has_image=page.has_image,
                    is_scanned=page.is_scanned,
                    text_confidence=page.confidence,
                )
                self.db.add(doc_page)

            # 保存元数据
            for key, value in parse_result.metadata.items():
                meta = DocumentMetadata(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    key=key,
                    value=str(value),
                )
                self.db.add(meta)

        except Exception as e:
            document.status = DocumentStatus.FAILED
            document.parsing_error = str(e)

        await self.db.flush()
        return document

    async def get_by_id(self, document_id: str, owner_id: Optional[str] = None) -> Document:
        query = select(Document).where(
            Document.id == document_id,
            Document.deleted_at.is_(None),
        )
        if owner_id:
            query = query.where(Document.owner_id == owner_id)
        result = await self.db.execute(query)
        doc = result.scalar_one_or_none()
        if not doc:
            raise NotFoundException("文档", document_id)
        return doc

    async def soft_delete(self, document: Document):
        """软删除文档"""
        from datetime import datetime, timezone
        document.deleted_at = datetime.now(timezone.utc)
        document.status = DocumentStatus.DELETED
        await self.db.flush()

    async def list_documents(
        self,
        owner_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[DocumentStatus] = None,
    ) -> Tuple[List[Document], int]:
        query = select(Document).where(Document.deleted_at.is_(None))

        if owner_id:
            query = query.where(Document.owner_id == owner_id)
        if keyword:
            query = query.where(Document.name.ilike(f"%{keyword}%"))
        if status:
            query = query.where(Document.status == status)

        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()

        query = query.order_by(Document.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        return result.scalars().all(), total

    def get_download_url(self, document: Document, expires: int = 3600) -> str:
        """获取文档下载预签名 URL"""
        return storage.get_presigned_url(
            document.storage_bucket, document.storage_path, expires
        )
