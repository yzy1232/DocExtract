"""
模板管理 API
"""
import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.template import (
    TemplateCreate, TemplateUpdate, TemplateOut, TemplateListOut,
    TemplateFieldCreate, TemplateFieldOut, TemplateCategoryCreate, TemplateCategoryOut,
    TemplateInferRequest, TemplateInferOut,
)
from app.schemas.common import ResponseBase, PaginatedResponse, PageInfo
from app.services.template_service import TemplateService
from app.core.auth import get_current_user
from app.models.user import User
from app.models.template import TemplateStatus

router = APIRouter(prefix="/templates", tags=["模板管理"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ResponseBase[TemplateOut], summary="创建模板")
async def create_template(
    data: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(
        "创建模板请求: user_id=%s name=%s field_count=%s is_public=%s",
        current_user.id,
        data.name,
        len(data.fields),
        data.is_public,
    )
    svc = TemplateService(db)
    template = await svc.create(data, current_user.id)
    logger.info("创建模板成功: template_id=%s user_id=%s", template.id, current_user.id)
    return ResponseBase(data=TemplateOut.model_validate(template))


@router.post("/infer-from-document", response_model=ResponseBase[TemplateInferOut], summary="从文档自动推断模板")
async def infer_template_from_document(
    data: TemplateInferRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(
        "模板自动推断请求: user_id=%s document_id=%s max_fields=%s template_name=%s",
        current_user.id,
        data.document_id,
        data.max_fields,
        data.template_name,
    )
    svc = TemplateService(db)
    inferred = await svc.infer_template_from_document(
        document_id=data.document_id,
        requester_id=current_user.id,
        requester_is_superuser=current_user.is_superuser,
        template_name=data.template_name,
        description=data.description,
        max_fields=data.max_fields,
    )
    logger.info(
        "模板自动推断成功: document_id=%s inferred_name=%s field_count=%s",
        data.document_id,
        inferred.get("name"),
        len(inferred.get("fields") or []),
    )
    infer_out = TemplateInferOut.model_validate(inferred)
    logger.info(
        "模板自动推断返回摘要: document_id=%s name=%s fields_type=%s field_count=%s first_field=%s",
        data.document_id,
        infer_out.name,
        type(infer_out.fields).__name__,
        len(infer_out.fields),
        infer_out.fields[0].model_dump() if infer_out.fields else None,
    )
    return ResponseBase(data=infer_out)


@router.post("/infer-from-document/stream", summary="从文档自动推断模板（流式）")
async def infer_template_from_document_stream(
    data: TemplateInferRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(
        "模板自动推断流式请求: user_id=%s document_id=%s max_fields=%s template_name=%s",
        current_user.id,
        data.document_id,
        data.max_fields,
        data.template_name,
    )

    svc = TemplateService(db)
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def on_chunk_done(payload: dict):
        await queue.put({"type": "progress", "data": payload})

    async def producer():
        try:
            inferred = await svc.infer_template_from_document(
                document_id=data.document_id,
                requester_id=current_user.id,
                requester_is_superuser=current_user.is_superuser,
                template_name=data.template_name,
                description=data.description,
                max_fields=data.max_fields,
                on_chunk_done=on_chunk_done,
            )
            infer_out = TemplateInferOut.model_validate(inferred)
            await queue.put({"type": "final", "data": infer_out.model_dump()})
            logger.info(
                "模板自动推断流式完成: document_id=%s field_count=%s",
                data.document_id,
                len(infer_out.fields),
            )
        except Exception as e:
            logger.exception("模板自动推断流式失败: document_id=%s error=%s", data.document_id, e)
            await queue.put({"type": "error", "data": {"message": str(e)}})
        finally:
            await queue.put({"type": "done"})

    async def stream_generator():
        producer_task = asyncio.create_task(producer())
        try:
            yield json.dumps({"type": "start", "data": {"document_id": data.document_id}}, ensure_ascii=False) + "\n"
            while True:
                item = await queue.get()
                event_type = item.get("type")
                if event_type == "done":
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            if not producer_task.done():
                producer_task.cancel()

    return StreamingResponse(
        stream_generator(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=ResponseBase[PaginatedResponse[TemplateListOut]], summary="查询模板列表")
async def list_templates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: Optional[str] = None,
    category_id: Optional[str] = None,
    status: Optional[TemplateStatus] = None,
    is_public: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    templates, total = await svc.list_templates(
        page=page, page_size=page_size, keyword=keyword,
        category_id=category_id, status=status, is_public=is_public,
    )
    items = []
    for t in templates:
        item = TemplateListOut.model_validate(t)
        item.field_count = len(t.fields)
        items.append(item)

    return ResponseBase(data=PaginatedResponse(
        items=items,
        pagination=PageInfo(
            page=page, page_size=page_size, total=total,
            total_pages=(total + page_size - 1) // page_size,
        ),
    ))


@router.get("/{template_id}", response_model=ResponseBase[TemplateOut], summary="获取模板详情")
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    template = await svc.get_by_id(template_id)
    return ResponseBase(data=TemplateOut.model_validate(template))


@router.put("/{template_id}", response_model=ResponseBase[TemplateOut], summary="更新模板")
async def update_template(
    template_id: str,
    data: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    template = await svc.get_by_id(template_id)
    updated = await svc.update(template, data, current_user.id)
    return ResponseBase(data=TemplateOut.model_validate(updated))


@router.delete("/{template_id}", response_model=ResponseBase[None], summary="删除模板")
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    template = await svc.get_by_id(template_id)
    await svc.delete(template)
    return ResponseBase(message="模板已归档删除")


@router.post("/{template_id}/fields", response_model=ResponseBase[TemplateFieldOut], summary="添加模板字段")
async def add_field(
    template_id: str,
    data: TemplateFieldCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    template = await svc.get_by_id(template_id)
    field = await svc.add_field(template, data, current_user.id)
    return ResponseBase(data=TemplateFieldOut.model_validate(field))


# =====================
# 模板分类
# =====================
@router.post("/categories", response_model=ResponseBase[TemplateCategoryOut], summary="创建模板分类")
async def create_category(
    data: TemplateCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    category = await svc.create_category(data)
    return ResponseBase(data=TemplateCategoryOut.model_validate(category))


@router.get("/categories/list", response_model=ResponseBase[list[TemplateCategoryOut]], summary="获取所有模板分类")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    categories = await svc.list_categories()
    return ResponseBase(data=[TemplateCategoryOut.model_validate(c) for c in categories])
