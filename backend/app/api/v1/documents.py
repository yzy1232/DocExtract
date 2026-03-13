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

router = APIRouter(prefix="/documents", tags=["文档管理"])


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
    mime_type = normalize_mime_type(file.content_type, safe_filename)
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
    for f in files:
        import os
        safe_filename = os.path.basename(f.filename or "unknown")
        content = await f.read()
        mime_type = normalize_mime_type(f.content_type, safe_filename)
        doc = await svc.upload(
            file_content=content,
            filename=safe_filename,
            mime_type=mime_type,
            owner_id=current_user.id,
        )
        results.append(DocumentOut.model_validate(doc))
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
