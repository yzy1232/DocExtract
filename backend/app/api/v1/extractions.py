"""
提取任务 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import io
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.extraction import (
    ExtractionCreate, BatchExtractionCreate, ExtractionTaskOut,
    ExtractionTaskListOut, ExtractionResultOut, ResultValidationUpdate, ExportRequest, TaskBatchAction
)
from app.schemas.common import ResponseBase, PaginatedResponse, PageInfo, MessageResponse
from app.services.extraction_service import ExtractionService
from app.core.auth import get_current_user
from app.models.user import User
from app.models.extraction import TaskStatus
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/extractions", tags=["提取任务"])


def _to_list_value(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _build_paginated_structured_result(structured_result, page: int, page_size: int):
    """将 structured_result 转为按行分页结果，避免一次返回超大载荷。"""
    if not isinstance(structured_result, dict) or not structured_result:
        return {
            "columns": [],
            "rows": [],
            "pagination": {
                "page": 1,
                "page_size": page_size,
                "total_rows": 0,
                "total_pages": 1,
            },
        }

    field_names = list(structured_result.keys())
    value_map = {name: _to_list_value(structured_result.get(name)) for name in field_names}
    total_rows = max((len(v) for v in value_map.values()), default=0)
    total_pages = max(1, (total_rows + page_size - 1) // page_size) if total_rows > 0 else 1
    safe_page = min(max(1, page), total_pages)

    start = (safe_page - 1) * page_size
    end = min(start + page_size, total_rows)

    rows = []
    for row_idx in range(start, end):
        row_data = {}
        for field_name in field_names:
            values = value_map[field_name]
            row_data[field_name] = values[row_idx] if row_idx < len(values) else None
        rows.append(row_data)

    return {
        "columns": [{"field_name": n, "field_label": n} for n in field_names],
        "rows": rows,
        "pagination": {
            "page": safe_page,
            "page_size": page_size,
            "total_rows": total_rows,
            "total_pages": total_pages,
        },
    }


@router.post("", response_model=ResponseBase[ExtractionTaskOut], summary="创建提取任务")
async def create_extraction(
    data: ExtractionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    task = await svc.create_task(data, current_user.id)
    return ResponseBase(data=ExtractionTaskOut.model_validate(task))


@router.post("/batch", response_model=ResponseBase[list[ExtractionTaskOut]], summary="批量提取")
async def batch_extraction(
    data: BatchExtractionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    tasks = await svc.create_batch_tasks(data, current_user.id)
    return ResponseBase(data=[ExtractionTaskOut.model_validate(t) for t in tasks])


@router.get("", response_model=ResponseBase[PaginatedResponse[ExtractionTaskListOut]], summary="查询提取任务列表")
async def list_extractions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    document_id: Optional[str] = None,
    status: Optional[TaskStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    creator_id = None if current_user.is_superuser else current_user.id
    tasks, total = await svc.list_tasks(
        creator_id=creator_id, document_id=document_id,
        status=status, page=page, page_size=page_size,
    )
    items = []
    for t in tasks:
        item = ExtractionTaskListOut.model_validate(t)
        item.document_name = t.document.name if t.document else None
        item.template_name = t.template.name if t.template else None
        items.append(item)
    return ResponseBase(data=PaginatedResponse(
        items=items,
        pagination=PageInfo(
            page=page, page_size=page_size, total=total,
            total_pages=(total + page_size - 1) // page_size,
        ),
    ))


@router.get("/{task_id}", response_model=ResponseBase[ExtractionTaskOut], summary="获取任务详情")
async def get_extraction(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    task = await svc.get_task_by_id(task_id)
    if not current_user.is_superuser and task.creator_id != current_user.id:
        raise ForbiddenException("无权限查看该任务")
    return ResponseBase(data=ExtractionTaskOut.model_validate(task))


@router.post("/{task_id}/restart", response_model=ResponseBase[ExtractionTaskOut], summary="重启失败任务")
async def restart_failed_extraction(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    task = await svc.get_task_by_id(task_id)
    if not current_user.is_superuser and task.creator_id != current_user.id:
        raise ForbiddenException("无权限重启该任务")
    restarted = await svc.restart_failed_task(task_id)
    return ResponseBase(data=ExtractionTaskOut.model_validate(restarted))


@router.delete("/{task_id}", response_model=ResponseBase[MessageResponse], summary="删除任务")
async def delete_extraction(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    task = await svc.get_task_by_id(task_id)
    if not current_user.is_superuser and task.creator_id != current_user.id:
        raise ForbiddenException("无权限删除该任务")
    action = await svc.delete_task(task_id)
    message = "任务已取消" if action == "cancelled" else "任务已删除"
    return ResponseBase(data=MessageResponse(message=message))


@router.post("/batch-restart", response_model=ResponseBase[dict], summary="批量重启失败任务")
async def batch_restart_failed_extractions(
    data: TaskBatchAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    success_ids = []
    failed_ids = []

    for task_id in data.task_ids:
        try:
            task = await svc.get_task_by_id(task_id)
            if not current_user.is_superuser and task.creator_id != current_user.id:
                raise ForbiddenException("无权限重启该任务")
            await svc.restart_failed_task(task_id)
            success_ids.append(task_id)
        except Exception as exc:
            failed_ids.append({"id": task_id, "reason": str(exc)})

    return ResponseBase(data={
        "success_ids": success_ids,
        "failed": failed_ids,
        "total": len(data.task_ids),
        "success_count": len(success_ids),
    })


@router.post("/batch-delete", response_model=ResponseBase[dict], summary="批量删除任务")
async def batch_delete_extractions(
    data: TaskBatchAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    success_ids = []
    failed_ids = []
    cancelled_count = 0
    deleted_count = 0

    for task_id in data.task_ids:
        try:
            task = await svc.get_task_by_id(task_id)
            if not current_user.is_superuser and task.creator_id != current_user.id:
                raise ForbiddenException("无权限删除该任务")
            action = await svc.delete_task(task_id)
            if action == "cancelled":
                cancelled_count += 1
            else:
                deleted_count += 1
            success_ids.append(task_id)
        except Exception as exc:
            failed_ids.append({"id": task_id, "reason": str(exc)})

    return ResponseBase(data={
        "success_ids": success_ids,
        "failed": failed_ids,
        "total": len(data.task_ids),
        "success_count": len(success_ids),
        "cancelled_count": cancelled_count,
        "deleted_count": deleted_count,
    })


@router.get("/{task_id}/results", response_model=ResponseBase[ExtractionResultOut], summary="获取提取结果")
async def get_extraction_results(
    task_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    paged: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import select
    from app.models.extraction import ExtractionResult
    from app.core.exceptions import NotFoundException
    svc = ExtractionService(db)
    task = await svc.get_task_by_id(task_id)
    if not current_user.is_superuser and task.creator_id != current_user.id:
        raise ForbiddenException("无权限查看该任务结果")

    result = await db.execute(
        select(ExtractionResult).where(ExtractionResult.task_id == task_id)
    )
    er = result.scalar_one_or_none()
    if not er:
        # 任务处理中尚未生成最终结果时，返回占位结果，避免前端误判“任务不存在”。
        if task.status in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.PROCESSING, TaskStatus.RETRYING):
            return ResponseBase(data=ExtractionResultOut(
                id=f"pending-{task_id}",
                task_id=task_id,
                structured_result=(
                    _build_paginated_structured_result({}, page, page_size)
                    if paged else {}
                ),
                overall_confidence=None,
                validation_status="pending",
                validation_notes=None,
                export_url=None,
                created_at=task.created_at,
                updated_at=task.updated_at,
            ))
        raise NotFoundException("提取结果", task_id)

    if not paged:
        return ResponseBase(data=ExtractionResultOut.model_validate(er))

    paged_structured_result = _build_paginated_structured_result(
        er.structured_result,
        page,
        page_size,
    )
    return ResponseBase(data=ExtractionResultOut(
        id=er.id,
        task_id=er.task_id,
        structured_result=paged_structured_result,
        overall_confidence=er.overall_confidence,
        validation_status=er.validation_status,
        validation_notes=er.validation_notes,
        export_url=er.export_url,
        created_at=er.created_at,
        updated_at=er.updated_at,
    ))


@router.put("/{task_id}/validation", response_model=ResponseBase[ExtractionResultOut], summary="验证提取结果")
async def validate_result(
    task_id: str,
    data: ResultValidationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    result = await svc.validate_result(task_id, data, current_user.id)
    return ResponseBase(data=ExtractionResultOut.model_validate(result))


@router.post("/export", response_model=ResponseBase[dict], summary="导出提取结果")
async def export_results(
    data: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    export_data = await svc.export_results(data.task_ids, data.format)
    return ResponseBase(data={
        "download_url": export_data["download_url"],
        "object_key": export_data["object_key"],
        "format": data.format,
    })


@router.get("/exports/download", summary="下载导出文件")
async def download_export_file(
    object_key: str = Query(..., description="导出对象存储路径"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = ExtractionService(db)
    content, content_type, filename = svc.get_export_file(object_key)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
