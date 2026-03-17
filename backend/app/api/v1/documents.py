"""
文档管理 API
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.extraction import DocumentOut, DocumentListOut, DocumentUpdate
from app.schemas.common import ResponseBase, PaginatedResponse, PageInfo, MessageResponse
from app.services.document_service import DocumentService
from app.core.auth import get_current_user
from app.models.user import User
from app.models.document import DocumentStatus
from app.config import settings
from app.processors.mime_resolver import normalize_mime_type
from fastapi.responses import StreamingResponse
import io
import asyncio
import logging
from urllib.parse import quote

router = APIRouter(prefix="/documents", tags=["文档管理"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=ResponseBase[DocumentOut], summary="上传单个文档")
async def upload_document(
    file: UploadFile = File(..., description="文档文件"),
    tags: Optional[str] = Query(default=None, description="标签(逗号分隔)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传单个文档并自动触发解析"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    # 安全检查：防止路径穿越
    import os
    safe_filename = os.path.basename(file.filename)
    mime_type = normalize_mime_type(file.content_type, safe_filename, default_text=False)
    file_content = await file.read()

    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    svc = DocumentService(db)
    document = await svc.upload(
        file_content=file_content,
        filename=safe_filename,
        mime_type=mime_type,
        owner_id=current_user.id,
        tags=tag_list,
    )

    # 先提交事务，再投递解析任务，避免 worker 读取不到未提交文档。
    await db.commit()
    try:
        from app.tasks.document_tasks import parse_document_task
        parse_document_task.delay(document.id)
    except Exception:
        logger.warning("触发文档解析任务失败，已忽略: document_id=%s", document.id, exc_info=True)

    return ResponseBase(data=DocumentOut.model_validate(document))


@router.post("/batch-upload", response_model=ResponseBase[list[DocumentOut]], summary="批量上传文档")
async def batch_upload(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(files) > settings.MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {settings.MAX_BATCH_SIZE} 个文件")

    svc = DocumentService(db)
    results = []
    document_ids = []
    for f in files:
        import os
        safe_filename = os.path.basename(f.filename or "unknown")
        content = await f.read()
        mime_type = normalize_mime_type(f.content_type, safe_filename, default_text=False)
        doc = await svc.upload(
            file_content=content,
            filename=safe_filename,
            mime_type=mime_type,
            owner_id=current_user.id,
        )
        document_ids.append(doc.id)
        results.append(DocumentOut.model_validate(doc))

    # 批量上传先统一提交，再批量投递任务，避免触发时序导致的文档不存在重试。
    await db.commit()
    from app.tasks.document_tasks import parse_document_task
    for document_id in document_ids:
        try:
            parse_document_task.delay(document_id)
        except Exception:
            logger.warning("触发文档解析任务失败，已忽略: document_id=%s", document_id, exc_info=True)

    return ResponseBase(data=results)


@router.get("", response_model=ResponseBase[PaginatedResponse[DocumentListOut]], summary="查询文档列表")
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: Optional[str] = None,
    status: Optional[DocumentStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = DocumentService(db)
    # 非超管只能查看自己的文档
    owner_id = None if current_user.is_superuser else current_user.id
    documents, total = await svc.list_documents(
        owner_id=owner_id, page=page, page_size=page_size,
        keyword=keyword, status=status,
    )
    return ResponseBase(data=PaginatedResponse(
        items=[DocumentListOut.model_validate(d) for d in documents],
        pagination=PageInfo(
            page=page, page_size=page_size, total=total,
            total_pages=(total + page_size - 1) // page_size,
        ),
    ))


@router.get("/{document_id}", response_model=ResponseBase[DocumentOut], summary="获取文档详情")
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = DocumentService(db)
    owner_id = None if current_user.is_superuser else current_user.id
    document = await svc.get_by_id(document_id, owner_id=owner_id)
    return ResponseBase(data=DocumentOut.model_validate(document))


@router.get("/{document_id}/download-url", response_model=ResponseBase[dict], summary="获取文档下载URL")
async def get_download_url(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = DocumentService(db)
    owner_id = None if current_user.is_superuser else current_user.id
    document = await svc.get_by_id(document_id, owner_id=owner_id)
    url = svc.get_download_url(document)
    return ResponseBase(data={"url": url, "expires_in": 3600})


@router.get("/{document_id}/status", response_model=ResponseBase[dict], summary="查询文档处理状态")
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = DocumentService(db)
    document = await svc.get_by_id(document_id)
    return ResponseBase(data={
        "id": document.id,
        "status": document.status.value,
        "page_count": document.page_count,
        "parsing_error": document.parsing_error,
    })


@router.put("/{document_id}", response_model=ResponseBase[DocumentOut], summary="更新文档信息")
async def update_document(
    document_id: str,
    data: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = DocumentService(db)
    document = await svc.get_by_id(document_id, owner_id=current_user.id)
    update_data = data.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(document, k, v)
    await db.flush()
    return ResponseBase(data=DocumentOut.model_validate(document))


@router.delete("/{document_id}", response_model=ResponseBase[MessageResponse], summary="删除文档")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = DocumentService(db)
    owner_id = None if current_user.is_superuser else current_user.id
    document = await svc.get_by_id(document_id, owner_id=owner_id)
    await svc.soft_delete(document)
    return ResponseBase(data=MessageResponse(message="文档已删除"))


@router.get("/{document_id}/download", summary="通过后端代理下载文档")
async def download_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """后端代理下载：由后端从对象存储拉取并转发给客户端，避免前端直接使用预签名 URL 导致的签名或跨域问题。"""
    svc = DocumentService(db)
    owner_id = None if current_user.is_superuser else current_user.id
    document = await svc.get_by_id(document_id, owner_id=owner_id)

    # 从存储下载（阻塞 IO，放到线程池中执行）
    from app.core.storage import storage

    try:
        content = await asyncio.to_thread(storage.download_file, document.storage_bucket, document.storage_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载文件失败: {str(e)}")

    filename = document.display_name or document.name or "download"
    # 为避免非 latin-1 字符导致的编码错误，按 RFC5987 提供 filename*，并提供 ASCII 回退
    def _ascii_fallback(name: str) -> str:
        try:
            name.encode('ascii')
            return name
        except UnicodeEncodeError:
            return ''.join(c if ord(c) < 128 else '_' for c in name)

    ascii_name = _ascii_fallback(filename)
    quoted = quote(filename)
    content_disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
    headers = {"Content-Disposition": content_disposition}
    return StreamingResponse(io.BytesIO(content), media_type=document.mime_type or "application/octet-stream", headers=headers)
