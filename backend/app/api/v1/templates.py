"""
模板管理 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.template import (
    TemplateCreate, TemplateUpdate, TemplateOut, TemplateListOut,
    TemplateFieldCreate, TemplateFieldOut, TemplateCategoryCreate, TemplateCategoryOut
)
from app.schemas.common import ResponseBase, PaginatedResponse, PageInfo
from app.services.template_service import TemplateService
from app.core.auth import get_current_user
from app.models.user import User
from app.models.template import TemplateStatus

router = APIRouter(prefix="/templates", tags=["模板管理"])


@router.post("", response_model=ResponseBase[TemplateOut], summary="创建模板")
async def create_template(
    data: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TemplateService(db)
    template = await svc.create(data, current_user.id)
    return ResponseBase(data=TemplateOut.model_validate(template))


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
