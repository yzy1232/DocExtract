"""
提取服务 - LLM 智能提取任务管理和执行
"""
import uuid
import time
import json
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models.extraction import (
    ExtractionTask, ExtractionResult, ExtractionField, ExtractionLog, TaskStatus, TaskPriority
)
from app.models.document import Document, DocumentStatus
from app.models.template import Template
from app.schemas.extraction import ExtractionCreate, BatchExtractionCreate, ResultValidationUpdate
from app.core.exceptions import NotFoundException, ValidationException
from app.llm.factory import get_adapter_by_provider, get_default_adapter, get_default_llm_config
from app.llm.prompt_engine import PromptEngine
from app.core.storage import storage
from app.config import settings


class ExtractionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_engine = PromptEngine()

    async def create_task(self, data: ExtractionCreate, creator_id: str) -> ExtractionTask:
        """创建提取任务并推送到队列"""
        # 验证文档和模板存在
        doc_result = await self.db.execute(select(Document).where(Document.id == data.document_id))
        document = doc_result.scalar_one_or_none()
        if not document:
            raise NotFoundException("文档", data.document_id)
        if document.status != DocumentStatus.PROCESSED:
            raise ValidationException(f"文档尚未解析完成，当前状态: {document.status.value}")

        tmpl_result = await self.db.execute(select(Template).where(Template.id == data.template_id))
        template = tmpl_result.scalar_one_or_none()
        if not template:
            raise NotFoundException("模板", data.template_id)

        provider = data.llm_provider or settings.DEFAULT_LLM_PROVIDER
        model = data.llm_model or settings.DEFAULT_LLM_MODEL

        task = ExtractionTask(
            id=str(uuid.uuid4()),
            document_id=data.document_id,
            template_id=data.template_id,
            creator_id=creator_id,
            status=TaskStatus.PENDING,
            priority=data.priority,
            llm_provider=provider,
            llm_model=model,
            llm_config_snapshot=data.extra_config,
            progress=0.0,
        )
        self.db.add(task)
        await self.db.flush()

        # 推送到 Celery 任务队列
        try:
            from app.tasks.extraction_tasks import run_extraction_task
            celery_task = run_extraction_task.apply_async(
                args=[task.id],
                queue="extraction",
                priority=self._priority_to_int(data.priority),
            )
            task.celery_task_id = celery_task.id
            task.status = TaskStatus.QUEUED
            await self.db.flush()
        except Exception:
            # Celery 不可用时，标记为待处理
            pass

        # 更新模板使用计数
        template.use_count += 1
        await self.db.flush()
        return task

    async def create_batch_tasks(self, data: BatchExtractionCreate, creator_id: str) -> List[ExtractionTask]:
        """批量创建提取任务"""
        tasks = []
        for doc_id in data.document_ids:
            task_data = ExtractionCreate(
                document_id=doc_id,
                template_id=data.template_id,
                priority=data.priority,
                llm_provider=data.llm_provider,
                llm_model=data.llm_model,
            )
            task = await self.create_task(task_data, creator_id)
            tasks.append(task)
        return tasks

    async def execute_extraction(self, task_id: str) -> ExtractionTask:
        """执行提取任务（由 Celery Worker 调用）"""
        result = await self.db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise NotFoundException("提取任务", task_id)

        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.now(timezone.utc)
        task.progress = 5.0
        await self.db.flush()
        await self._log(task_id, "info", "extraction_start", "开始执行提取任务")

        start_time = time.time()
        try:
            # 获取文档内容
            doc_result = await self.db.execute(
                select(Document).where(Document.id == task.document_id)
            )
            document = doc_result.scalar_one()

            file_content = storage.download_file(document.storage_bucket, document.storage_path)

            from app.processors.factory import get_processor
            processor = get_processor(document.mime_type)
            parse_result = await processor.parse(file_content, document.name)
            document_content = parse_result.full_text

            task.progress = 30.0
            await self.db.flush()

            # 获取模板和字段
            tmpl_result = await self.db.execute(
                select(Template).where(Template.id == task.template_id)
            )
            template = tmpl_result.scalar_one()

            fields_data = [
                {
                    "name": f.name,
                    "display_name": f.display_name,
                    "field_type": f.field_type.value if hasattr(f.field_type, "value") else f.field_type,
                    "description": f.description,
                    "required": f.required,
                    "extraction_hints": f.extraction_hints,
                    "validation_rules": f.validation_rules,
                }
                for f in template.fields
            ]

            task.progress = 40.0
            task.progress_message = "正在调用LLM提取..."
            await self.db.flush()

            # 构建提示词并调用 LLM
            messages = self.prompt_engine.build_extraction_messages(
                document_content=document_content,
                template_fields=fields_data,
                system_prompt=template.system_prompt,
                extraction_prompt_template=template.extraction_prompt_template,
                few_shot_examples=template.few_shot_examples,
            )

            adapter = get_adapter_by_provider(task.llm_provider or settings.DEFAULT_LLM_PROVIDER)
            llm_config = get_default_llm_config(task.llm_provider, task.llm_model)
            llm_response = await adapter.chat(messages, llm_config)

            task.token_used = llm_response.total_tokens
            task.progress = 80.0
            await self.db.flush()

            # 解析 LLM 响应
            parsed = self.prompt_engine.parse_llm_response(llm_response.content)
            extracted_fields = parsed.get("fields", {})

            # 保存字段级结果
            structured_result = {}
            total_confidence = 0.0
            valid_count = 0
            for field_def in template.fields:
                field_val = extracted_fields.get(field_def.name, {})
                raw_value = field_val.get("value")
                confidence = float(field_val.get("confidence", 0.0))
                source_text = field_val.get("source_text", "")

                normalized_value = self._normalize_value(raw_value, field_def.field_type)
                is_valid, validation_error = self._validate_value(
                    normalized_value, field_def.required, field_def.validation_rules
                )

                ef = ExtractionField(
                    id=str(uuid.uuid4()),
                    task_id=task_id,
                    field_id=field_def.id,
                    field_name=field_def.name,
                    raw_value=str(raw_value) if raw_value is not None else None,
                    normalized_value=str(normalized_value) if normalized_value is not None else None,
                    value_type=field_def.field_type.value if hasattr(field_def.field_type, "value") else field_def.field_type,
                    confidence=confidence,
                    is_valid=is_valid,
                    validation_error=validation_error,
                    source_text=source_text[:500] if source_text else None,
                    extraction_method="llm",
                )
                self.db.add(ef)
                structured_result[field_def.name] = normalized_value

                if confidence > 0:
                    total_confidence += confidence
                    valid_count += 1

            overall_confidence = total_confidence / valid_count if valid_count > 0 else 0.0

            # 保存汇总结果
            extraction_result = ExtractionResult(
                id=str(uuid.uuid4()),
                task_id=task_id,
                raw_result=parsed,
                structured_result=structured_result,
                overall_confidence=overall_confidence,
                validation_status="pending",
            )
            self.db.add(extraction_result)

            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc)
            task.progress = 100.0
            task.progress_message = "提取完成"
            task.processing_time_ms = int((time.time() - start_time) * 1000)
            await self._log(task_id, "info", "extraction_complete", f"提取完成，置信度: {overall_confidence:.2f}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.processing_time_ms = int((time.time() - start_time) * 1000)
            await self._log(task_id, "error", "extraction_failed", str(e))

        await self.db.flush()
        return task

    def _normalize_value(self, value: Any, field_type) -> Any:
        """标准化字段值"""
        if value is None:
            return None
        field_type_str = field_type.value if hasattr(field_type, "value") else str(field_type)
        if field_type_str == "number":
            try:
                return float(str(value).replace(",", "").strip())
            except (ValueError, TypeError):
                return value
        if field_type_str in ("date", "datetime"):
            return str(value).strip()
        if field_type_str == "boolean":
            return str(value).lower() in ("true", "yes", "是", "1")
        return str(value).strip() if value else None

    def _validate_value(self, value: Any, required: bool, rules: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """验证字段值"""
        if required and (value is None or value == ""):
            return False, "必填字段未提取到值"
        if value is not None and rules:
            import re
            pattern = rules.get("pattern")
            if pattern and not re.match(pattern, str(value)):
                return False, f"格式不匹配: {pattern}"
            min_val = rules.get("min")
            max_val = rules.get("max")
            if min_val is not None and isinstance(value, (int, float)) and value < min_val:
                return False, f"值 {value} 小于最小值 {min_val}"
            if max_val is not None and isinstance(value, (int, float)) and value > max_val:
                return False, f"值 {value} 大于最大值 {max_val}"
        return True, None

    async def _log(self, task_id: str, level: str, stage: str, message: str, extra: dict = None):
        log = ExtractionLog(
            id=str(uuid.uuid4()),
            task_id=task_id,
            level=level,
            stage=stage,
            message=message,
            extra_data=extra or {},
        )
        self.db.add(log)

    def _priority_to_int(self, priority: TaskPriority) -> int:
        return {"low": 1, "normal": 5, "high": 7, "urgent": 9}.get(priority.value, 5)

    async def get_task_by_id(self, task_id: str) -> ExtractionTask:
        result = await self.db.execute(
            select(ExtractionTask).where(ExtractionTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise NotFoundException("提取任务", task_id)
        return task

    async def list_tasks(
        self,
        creator_id: Optional[str] = None,
        document_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ExtractionTask], int]:
        query = select(ExtractionTask)
        if creator_id:
            query = query.where(ExtractionTask.creator_id == creator_id)
        if document_id:
            query = query.where(ExtractionTask.document_id == document_id)
        if status:
            query = query.where(ExtractionTask.status == status)

        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()

        query = (
            query.options(
                selectinload(ExtractionTask.document),
                selectinload(ExtractionTask.template),
            )
            .order_by(ExtractionTask.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        return result.scalars().all(), total

    async def validate_result(
        self, task_id: str, data: ResultValidationUpdate, validator_id: str
    ) -> ExtractionResult:
        """人工验证结果"""
        result_query = await self.db.execute(
            select(ExtractionResult).where(ExtractionResult.task_id == task_id)
        )
        extraction_result = result_query.scalar_one_or_none()
        if not extraction_result:
            raise NotFoundException("提取结果", task_id)

        extraction_result.validation_status = data.validation_status
        extraction_result.validation_notes = data.validation_notes
        extraction_result.validated_by = validator_id
        extraction_result.validated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return extraction_result

    async def export_results(self, task_ids: List[str], export_format: str) -> str:
        """导出提取结果，返回下载 URL"""
        results = []
        for task_id in task_ids:
            result_query = await self.db.execute(
                select(ExtractionResult).where(ExtractionResult.task_id == task_id)
            )
            er = result_query.scalar_one_or_none()
            if er:
                results.append({"task_id": task_id, **er.structured_result})

        if export_format == "json":
            content = json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8")
            content_type = "application/json"
            ext = "json"
        else:
            # 默认 xlsx
            import openpyxl, io
            wb = openpyxl.Workbook()
            ws = wb.active
            if results:
                ws.append(list(results[0].keys()))
                for row in results:
                    ws.append([str(v) if v is not None else "" for v in row.values()])
            buf = io.BytesIO()
            wb.save(buf)
            content = buf.getvalue()
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ext = "xlsx"

        export_key = storage.build_result_key(f"export_{uuid.uuid4().hex[:8]}", ext)
        storage.upload_bytes(settings.STORAGE_BUCKET_RESULTS, export_key, content, content_type)
        return storage.get_presigned_url(settings.STORAGE_BUCKET_RESULTS, export_key, 3600)
