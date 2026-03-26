"""
提取服务 - LLM 智能提取任务管理和执行
"""
import asyncio
import uuid
import time
import json
import re
import logging
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timezone
from urllib.parse import quote
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from app.models.extraction import (
    ExtractionTask, ExtractionResult, ExtractionField, ExtractionLog, TaskStatus, TaskPriority
)
from app.models.document import Document, DocumentStatus
from app.models.template import Template
from app.models.system import LLMConfig as LLMConfigModel, SystemConfig
from app.schemas.extraction import ExtractionCreate, BatchExtractionCreate, ResultValidationUpdate
from app.core.exceptions import NotFoundException, ValidationException
from app.llm.factory import get_adapter_by_provider, get_default_llm_config, create_adapter_from_db_config
from app.llm.prompt_engine import PromptEngine
from app.llm.base_adapter import LLMMessage
from app.core.storage import storage
from app.config import settings
from app.processors.mime_resolver import normalize_mime_type


EXTRACTION_CHUNK_SIZE = 3000
EXTRACTION_CHUNK_OVERLAP = 500
EXTRACTION_CROSS_VALIDATE_ROUNDS = 2
EXTRACTION_MIN_AGREEMENT = 2
EXTRACTION_STALE_TIMEOUT_SECONDS = 300
LLM_IO_LOG_MAX_CHARS = 8000
EXCEL_FIELD_SAMPLE_LIMIT = 60
EXTRACTION_CHUNK_CONCURRENCY = 3


logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_engine = PromptEngine()

    async def _checkpoint_progress(
        self,
        task: ExtractionTask,
        progress: float,
        message: Optional[str] = None,
    ):
        """持久化任务进度，保证轮询可见中间态。"""
        task.progress = round(max(0.0, min(100.0, float(progress))), 2)
        if message is not None:
            task.progress_message = message
        # 每次进度落库都强制刷新时间戳，作为“收到阶段结果后重置超时计时器”的心跳。
        task.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.commit()

    def _truncate_log_text(self, value: Any, max_chars: Optional[int] = None) -> str:
        """日志文本截断，防止大文档导致日志过长。"""
        limit = int(max_chars or getattr(settings, "LLM_IO_LOG_MAX_CHARS", LLM_IO_LOG_MAX_CHARS))
        limit = max(500, limit)

        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False)
            except Exception:
                text = str(value)

        if len(text) <= limit:
            return text
        return f"{text[:limit]}... [truncated {len(text) - limit} chars]"

    def _build_structured_preview_from_chunk(self, chunk_result: Dict[str, Any]) -> Dict[str, Any]:
        """将单个分块结果转换为可直接展示的结构化预览。"""
        fields = chunk_result.get("fields", {}) if isinstance(chunk_result, dict) else {}
        if not isinstance(fields, dict):
            return {}

        preview: Dict[str, Any] = {}
        for field_name, field_obj in fields.items():
            if not isinstance(field_obj, dict):
                continue
            preview[field_name] = field_obj.get("value")
        return preview

    def _parse_confidence(self, value: Any, default: float = 0.0) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = default
        return max(0.0, min(1.0, confidence))

    def _safe_excel_header_name(self, value: Any, col_idx: int) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            text = f"column_{col_idx + 1}"
        return text[:64]

    def _looks_like_numeric_or_date(self, value: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        if re.match(r"^-?\d+(\.\d+)?$", text.replace(",", "")):
            return True
        if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", text):
            return True
        if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", text):
            return True
        return False

    def _detect_excel_header_row_rule_based(self, sample_rows: List[List[str]]) -> Dict[str, Any]:
        """规则识别表头行，不依赖 LLM。"""
        if not sample_rows:
            return {
                "header_row_index": 1,
                "confidence": 0.5,
                "headers": [],
                "reason": "无可用样本，默认首行为表头",
            }

        best_idx = 1
        best_score = float("-inf")
        second_score = float("-inf")

        for idx, row in enumerate(sample_rows, start=1):
            cells = [str(c).strip() if c is not None else "" for c in row]
            non_empty = [c for c in cells if c]
            if not non_empty:
                score = -100.0
            else:
                non_empty_count = len(non_empty)
                numeric_like = sum(1 for c in non_empty if self._looks_like_numeric_or_date(c))
                text_like = sum(1 for c in non_empty if not self._looks_like_numeric_or_date(c))
                unique_ratio = len(set(non_empty)) / max(1, non_empty_count)

                score = (
                    non_empty_count * 1.2
                    + text_like * 1.5
                    - numeric_like * 0.9
                    + unique_ratio
                )
                if idx == 1:
                    score += 0.4

            if score > best_score:
                second_score = best_score
                best_score = score
                best_idx = idx
            elif score > second_score:
                second_score = score

        margin = best_score - second_score if second_score != float("-inf") else 1.0
        confidence = max(0.6, min(0.99, 0.7 + margin * 0.05))
        best_headers = sample_rows[best_idx - 1] if best_idx - 1 < len(sample_rows) else []

        return {
            "header_row_index": best_idx,
            "confidence": round(confidence, 4),
            "headers": [str(x).strip() for x in best_headers],
            "reason": "rule_based_header_detection",
        }

    def _build_excel_field_storage_value(self, values: List[Any]) -> Tuple[Optional[str], Optional[str]]:
        """为字段级明细存储构建摘要，避免超长写入 DB。"""
        if not values:
            return None, None

        sample = values[:EXCEL_FIELD_SAMPLE_LIMIT]
        payload = {
            "count": len(values),
            "sample": sample,
        }
        raw_value = json.dumps(payload, ensure_ascii=False)

        normalized_payload = {
            "count": len(values),
            "sample": sample[:10],
        }
        normalized_value = json.dumps(normalized_payload, ensure_ascii=False)
        return raw_value, normalized_value

    def _collect_excel_sheet_rows(self, parse_result) -> List[Dict[str, Any]]:
        """从解析结果中收集每个sheet的二维行数据。"""
        sheets: List[Dict[str, Any]] = []

        for page_idx, page in enumerate(parse_result.pages or [], start=1):
            table = (page.tables or [None])[0]
            if not isinstance(table, dict):
                continue

            headers = table.get("headers") if isinstance(table.get("headers"), list) else []
            data_rows = table.get("rows") if isinstance(table.get("rows"), list) else []
            all_rows = [headers] + data_rows if headers else data_rows

            normalized_rows: List[List[str]] = []
            for row in all_rows:
                if not isinstance(row, list):
                    continue
                row_cells = [str(cell).strip() if cell is not None else "" for cell in row]
                if any(cell for cell in row_cells):
                    normalized_rows.append(row_cells)

            if not normalized_rows:
                continue

            sheets.append({
                "sheet_index": page_idx,
                "sheet_name": str(table.get("sheet") or f"Sheet{page_idx}"),
                "rows": normalized_rows,
            })

        return sheets

    async def _detect_excel_header_row(self, adapter, llm_config, sheet_name: str, sample_rows: List[List[str]]) -> Dict[str, Any]:
        """基于前5行让 LLM 识别表头所在行。"""
        serialized_rows = [
            {"row_index": idx, "cells": row}
            for idx, row in enumerate(sample_rows, start=1)
        ]

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是电子表格结构识别助手。你的任务是从候选行中找出最可能的字段表头行。"
                    "仅输出JSON，不要输出解释。"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"请分析sheet: {sheet_name} 的前{len(sample_rows)}行。\n"
                    "规则：字段表头行通常包含字段名称，数据行通常更像数值/明细。\n"
                    "返回JSON格式："
                    "{\"header_row_index\": 1到5之间整数, \"confidence\": 0到1小数, \"headers\": [字符串], \"reason\": \"简短原因\"}\n"
                    "如果无法判断，header_row_index返回1。\n\n"
                    f"候选行数据: {json.dumps(serialized_rows, ensure_ascii=False)}"
                ),
            ),
        ]

        response = await adapter.chat(messages, llm_config)
        parsed = self.prompt_engine.parse_llm_response(response.content)
        parsed["_token_used"] = response.total_tokens or 0
        return parsed

    def _build_excel_structured_result(
        self,
        all_rows: List[List[str]],
        header_row_index: int,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """根据识别出的表头行构建结构化列结果与行记录。"""
        if not all_rows:
            return {}, []

        safe_index = max(1, min(header_row_index, len(all_rows)))
        headers = all_rows[safe_index - 1]
        max_cols = max((len(r) for r in all_rows), default=0)

        normalized_headers: List[str] = []
        used_names = set()
        for col_idx in range(max_cols):
            header_cell = headers[col_idx] if col_idx < len(headers) else ""
            base_name = self._safe_excel_header_name(header_cell, col_idx)
            final_name = base_name
            seq = 2
            while final_name in used_names:
                suffix = f"_{seq}"
                final_name = f"{base_name[:64 - len(suffix)]}{suffix}"
                seq += 1
            used_names.add(final_name)
            normalized_headers.append(final_name)

        records: List[Dict[str, Any]] = []
        for row in all_rows[safe_index:]:
            record: Dict[str, Any] = {}
            has_value = False
            for col_idx, field_name in enumerate(normalized_headers):
                value = row[col_idx] if col_idx < len(row) else ""
                value = value.strip() if isinstance(value, str) else value
                if value == "":
                    value = None
                if value is not None:
                    has_value = True
                record[field_name] = value
            if has_value:
                records.append(record)

        structured: Dict[str, Any] = {}
        for field_name in normalized_headers:
            col_values = [rec.get(field_name) for rec in records if rec.get(field_name) is not None]
            structured[field_name] = col_values

        return structured, records

    async def _execute_excel_extraction(
        self,
        task: ExtractionTask,
        task_id: str,
        parse_result,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, int]:
        """Excel 专用提取流程：规则识别表头并直接落库（不调用LLM）。"""
        await self._checkpoint_progress(task, 40.0, "Excel表头识别中...")

        sheets = self._collect_excel_sheet_rows(parse_result)
        if not sheets:
            raise ValidationException("Excel解析结果为空，未识别到有效数据行")

        structured_result: Dict[str, Any] = {}
        raw_sheet_results: List[Dict[str, Any]] = []
        total_tokens = 0
        confidences: List[float] = []

        for idx, sheet in enumerate(sheets, start=1):
            all_rows = sheet["rows"]
            sample_rows = all_rows[:5]

            infer_result = self._detect_excel_header_row_rule_based(sample_rows)

            header_row_index = infer_result.get("header_row_index")
            try:
                header_row_index = int(header_row_index)
            except (TypeError, ValueError):
                header_row_index = 1
            header_row_index = max(1, min(header_row_index, min(5, len(all_rows))))

            confidence = self._parse_confidence(infer_result.get("confidence"), default=0.7)
            confidences.append(confidence)

            sheet_structured, sheet_records = self._build_excel_structured_result(all_rows, header_row_index)

            for key, value in sheet_structured.items():
                merged_key = key
                if merged_key in structured_result:
                    merged_key = f"{sheet['sheet_name']}:{key}"[:64]
                structured_result[merged_key] = value

                raw_value, normalized_value = self._build_excel_field_storage_value(value if isinstance(value, list) else [])

                ef = ExtractionField(
                    id=str(uuid.uuid4()),
                    task_id=task_id,
                    field_id=None,
                    field_name=merged_key,
                    raw_value=raw_value,
                    normalized_value=normalized_value,
                    value_type="list_summary",
                    confidence=confidence,
                    is_valid=True,
                    validation_error=None,
                    source_text=f"sheet={sheet['sheet_name']}; header_row={header_row_index}; value_count={len(value) if isinstance(value, list) else 0}",
                    extraction_method="excel_rule_based",
                )
                self.db.add(ef)

            raw_sheet_results.append({
                "sheet_index": sheet["sheet_index"],
                "sheet_name": sheet["sheet_name"],
                "header_row_index": header_row_index,
                "confidence": confidence,
                "headers": infer_result.get("headers") if isinstance(infer_result.get("headers"), list) else [],
                "reason": str(infer_result.get("reason") or ""),
                "sample_rows": sample_rows,
                "records_preview": sheet_records[:20],
            })

            await self._checkpoint_progress(
                task,
                40.0 + (idx / len(sheets)) * 45.0,
                f"Excel表头识别完成（{idx}/{len(sheets)}）",
            )

        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "stage": "completed",
            "mode": "excel_rule_based_header_detection",
            "sheets": raw_sheet_results,
            "note": "Excel使用规则进行表头识别并直接入库，未调用LLM",
        }, structured_result, overall_confidence, total_tokens

    def _finalize_merged_result(self, merged: Dict[str, Any], field_names: List[str]) -> Dict[str, Any]:
        """最终阶段对合并结果做去重和稳定排序。"""
        records = merged.get("records", []) if isinstance(merged, dict) else []
        deduped_records: List[Dict[str, Any]] = []
        seen_record_keys = set()
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            normalized_record = {k: record.get(k) for k in field_names}
            rec_key = self._stable_dump(normalized_record)
            if rec_key in seen_record_keys:
                continue
            seen_record_keys.add(rec_key)
            deduped_records.append(normalized_record)

        deduped_records.sort(key=lambda item: self._stable_dump(item))

        merged_fields = merged.get("fields", {}) if isinstance(merged, dict) else {}
        finalized_fields: Dict[str, Dict[str, Any]] = {}
        for field_name in field_names:
            field_obj = merged_fields.get(field_name, {}) if isinstance(merged_fields, dict) else {}
            if not isinstance(field_obj, dict):
                field_obj = {}

            value = field_obj.get("value")
            if isinstance(value, list):
                deduped_values: List[Any] = []
                seen_value_keys = set()
                for item in value:
                    value_key = self._stable_dump(item)
                    if value_key in seen_value_keys:
                        continue
                    seen_value_keys.add(value_key)
                    deduped_values.append(item)
                deduped_values.sort(key=lambda item: self._stable_dump(item))
                normalized_value: Any = deduped_values
            else:
                normalized_value = value

            finalized_fields[field_name] = {
                "value": normalized_value,
                "confidence": field_obj.get("confidence", 0.0),
                "source_text": field_obj.get("source_text", ""),
            }

        return {
            "fields": finalized_fields,
            "records": deduped_records,
            "extraction_notes": merged.get("extraction_notes", "") if isinstance(merged, dict) else "",
        }

    async def _resolve_task_adapter_and_config(self, task: ExtractionTask):
        """解析提取任务的 LLM 适配器与配置。

        优先级：
        1. 任务快照中的 base_url/api_key
        2. 系统默认 LLM 配置（SystemConfig.default_llm_config_id -> LLMConfig）
        3. 代码环境变量配置（向后兼容）
        """
        llm_config = get_default_llm_config(task.llm_provider, task.llm_model)

        snapshot = task.llm_config_snapshot or {}
        snapshot_api_key = snapshot.get("api_key") or snapshot.get("api_key_encrypted")
        snapshot_base_url = snapshot.get("base_url")
        snapshot_provider = snapshot.get("provider") or task.llm_provider or "custom"
        snapshot_model = task.llm_model or snapshot.get("model_name") or snapshot.get("model")

        if snapshot_api_key and snapshot_base_url:
            if snapshot_model:
                llm_config.model = snapshot_model
            adapter = create_adapter_from_db_config(
                snapshot_api_key,
                snapshot_base_url,
                provider=snapshot_provider,
                model=llm_config.model,
            )
            return adapter, llm_config

        # 若快照中无密钥，尝试读取系统默认 LLM 配置
        try:
            sc_result = await self.db.execute(
                select(SystemConfig).where(SystemConfig.key == "default_llm_config_id")
            )
            sc = sc_result.scalar_one_or_none()
            default_cfg_id = sc.value if sc and sc.value else None

            if default_cfg_id:
                cfg_result = await self.db.execute(
                    select(LLMConfigModel).where(
                        LLMConfigModel.id == default_cfg_id,
                        LLMConfigModel.is_active == True,
                    )
                )
                cfg = cfg_result.scalar_one_or_none()
                if cfg and cfg.api_key_encrypted and cfg.base_url:
                    llm_config.model = task.llm_model or cfg.model_name or llm_config.model
                    adapter = create_adapter_from_db_config(
                        cfg.api_key_encrypted,
                        cfg.base_url,
                        provider=task.llm_provider or "custom",
                        model=llm_config.model,
                    )
                    return adapter, llm_config
        except Exception:
            # 读取系统配置失败时回退到环境变量配置
            pass

        adapter = get_adapter_by_provider(task.llm_provider or settings.DEFAULT_LLM_PROVIDER)
        return adapter, llm_config

    def _normalize_task_progress(self, task: ExtractionTask):
        """统一任务进度显示，避免前后端状态与进度不一致。"""
        progress = round(max(0.0, min(100.0, float(task.progress or 0.0))), 2)
        if task.status == TaskStatus.COMPLETED:
            task.progress = 100.0
            return
        task.progress = progress

    def _sync_task_status_from_celery(self, task: ExtractionTask) -> bool:
        """根据 Celery 实时状态修正任务展示状态，降低排队态滞后。"""
        if not task.celery_task_id:
            return False

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False

        try:
            from app.tasks.celery_app import celery_app

            async_result = celery_app.AsyncResult(task.celery_task_id)
            runtime_state = (async_result.state or "").upper()
        except Exception:
            return False

        changed = False

        if runtime_state == "STARTED" and task.status in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RETRYING):
            task.status = TaskStatus.PROCESSING
            task.started_at = task.started_at or datetime.now(timezone.utc)
            if not task.progress_message or "入队" in task.progress_message or "待调度" in task.progress_message:
                task.progress_message = "任务处理中"
            changed = True
        elif runtime_state == "RETRY":
            # Celery 可能出现短暂 RETRY 过渡态；避免新建任务被误显示为“重试中”。
            # 仅当任务已处于重试流程（如手动重启失败任务）时保留该状态。
            if task.status == TaskStatus.RETRYING:
                task.progress_message = task.progress_message or "任务重试中"

        return changed

    def _is_excel_document(self, document: Document) -> bool:
        normalized_mime = normalize_mime_type(document.mime_type, document.name)
        return (
            normalized_mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            or (document.name and document.name.lower().endswith(".xlsx"))
        )

    def _is_stale_running_task(self, task: ExtractionTask) -> bool:
        if task.status not in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.PROCESSING, TaskStatus.RETRYING):
            return False
        if not task.updated_at:
            return False

        timeout_seconds = int(getattr(settings, "EXTRACTION_STALE_TIMEOUT_SECONDS", EXTRACTION_STALE_TIMEOUT_SECONDS))
        timeout_seconds = max(60, timeout_seconds)

        if task.updated_at.tzinfo:
            now = datetime.now(task.updated_at.tzinfo)
        else:
            now = datetime.utcnow()

        age_seconds = (now - task.updated_at).total_seconds()
        return age_seconds >= timeout_seconds

    def _mark_task_stale_failed(self, task: ExtractionTask):
        if not self._is_stale_running_task(task):
            return

        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now(timezone.utc)
        task.progress_message = "任务处理超时，已自动标记失败"
        stale_error = "stale-sync: task exceeded processing timeout and was auto-marked failed"
        if task.error_message:
            if stale_error not in task.error_message:
                task.error_message = f"{task.error_message} | {stale_error}"
        else:
            task.error_message = stale_error

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

        # 先提交任务主记录，避免 Celery 过快消费时读不到未提交事务中的任务。
        template.use_count += 1
        await self.db.flush()
        await self.db.commit()

        # 推送到 Celery 任务队列（Excel 与非 Excel 统一异步执行，保证创建请求快速返回）
        try:
            from app.tasks.extraction_tasks import run_extraction_task
            celery_task = run_extraction_task.apply_async(
                args=[task.id],
                queue="extraction",
                priority=self._priority_to_int(data.priority),
            )
            task.celery_task_id = celery_task.id
            task.status = TaskStatus.QUEUED
            task.progress_message = "任务已入队"
        except Exception:
            # Celery 不可用时，标记为待处理
            task.status = TaskStatus.PENDING
            task.progress_message = "队列不可用，任务待调度"

        await self.db.flush()
        await self.db.commit()

        # 避免 API 序列化阶段触发异步懒加载（MissingGreenlet）
        await self.db.refresh(task, attribute_names=["created_at", "updated_at", "results", "field_results"])
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

        # 幂等保护：重投或重复消费时不重复执行终态任务。
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            self._normalize_task_progress(task)
            return task

        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.now(timezone.utc)
        await self._checkpoint_progress(task, 5.0, "任务启动")
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
            normalized_mime = normalize_mime_type(document.mime_type, document.name)
            processor = get_processor(normalized_mime)
            if not processor:
                raise ValidationException(f"文档不支持解析，MIME={normalized_mime}")
            parse_result = await processor.parse(file_content, document.name)
            document_content = parse_result.full_text

            await self._checkpoint_progress(task, 30.0, "文档解析完成")

            logger.info(
                "Excel detection params: normalized_mime=%s, document_name=%s",
                normalized_mime,
                document.name,
            )
            is_excel_doc = (
                normalized_mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or
                (document.name and document.name.lower().endswith(".xlsx"))
            )

            result_row_query = await self.db.execute(
                select(ExtractionResult).where(ExtractionResult.task_id == task_id)
            )
            extraction_result = result_row_query.scalar_one_or_none()
            if not extraction_result:
                extraction_result = ExtractionResult(
                    id=str(uuid.uuid4()),
                    task_id=task_id,
                    raw_result={
                        "stage": "processing",
                    },
                    structured_result={},
                    overall_confidence=0.0,
                    validation_status="pending",
                )
                self.db.add(extraction_result)
                await self.db.flush()
                await self.db.commit()

            if is_excel_doc:
                raw_result, structured_result, overall_confidence, token_used = await self._execute_excel_extraction(
                    task,
                    task_id,
                    parse_result,
                )

                extraction_result.raw_result = raw_result
                extraction_result.structured_result = structured_result
                extraction_result.overall_confidence = overall_confidence

                task.token_used = token_used
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(timezone.utc)
                task.progress = 100.0
                task.progress_message = "提取完成（Excel表头识别）"
                task.processing_time_ms = int((time.time() - start_time) * 1000)

                await self._log(task_id, "info", "extraction_complete", f"Excel表头识别完成，置信度: {overall_confidence:.2f}")
                await self.db.flush()
                await self.db.commit()
                return task

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

            await self._checkpoint_progress(task, 40.0, "正在调用LLM提取...")

            adapter, llm_config = await self._resolve_task_adapter_and_config(task)
            chunk_size = getattr(settings, "EXTRACTION_CHUNK_SIZE", EXTRACTION_CHUNK_SIZE)
            chunk_overlap = getattr(settings, "EXTRACTION_CHUNK_OVERLAP", EXTRACTION_CHUNK_OVERLAP)
            cross_validate_rounds = max(1, int(getattr(settings, "EXTRACTION_CROSS_VALIDATE_ROUNDS", EXTRACTION_CROSS_VALIDATE_ROUNDS)))
            min_agreement = max(1, int(getattr(settings, "EXTRACTION_MIN_AGREEMENT", EXTRACTION_MIN_AGREEMENT)))
            min_agreement = min(min_agreement, cross_validate_rounds)
            content_chunks = self._split_text_with_overlap(document_content, chunk_size, chunk_overlap)
            chunk_concurrency = max(1, int(getattr(settings, "EXTRACTION_CHUNK_CONCURRENCY", EXTRACTION_CHUNK_CONCURRENCY)))
            
            # 诊断日志：记录分段信息
            logger.info(
                "启动分段并发提取 task_id=%s doc_len=%s chunk_size=%s overlap=%s total_chunks=%s concurrency=%s rounds=%s",
                task_id,
                len(document_content),
                chunk_size,
                chunk_overlap,
                len(content_chunks),
                chunk_concurrency,
                cross_validate_rounds,
            )

            parsed_chunks = []
            chunk_round_parsed = []
            total_tokens = 0
            total_chunks = len(content_chunks)
            total_calls = max(1, total_chunks * cross_validate_rounds)
            completed_calls = 0
            field_names = [f.name for f in template.fields]
            chunk_semaphore = asyncio.Semaphore(chunk_concurrency)

            extraction_result.raw_result = {
                "stage": "processing",
                "total_chunks": total_chunks,
                "processed_chunks": 0,
                "partial_chunks": [],
                "chunk_concurrency": chunk_concurrency,
            }
            await self.db.flush()
            await self.db.commit()

            chunk_tasks = [
                asyncio.create_task(
                    self._extract_single_chunk_with_cross_validation(
                        task_id=task_id,
                        chunk_index=idx,
                        total_chunks=total_chunks,
                        chunk_content=chunk_content,
                        adapter=adapter,
                        llm_config=llm_config,
                        template=template,
                        fields_data=fields_data,
                        field_names=field_names,
                        cross_validate_rounds=cross_validate_rounds,
                        min_agreement=min_agreement,
                        semaphore=chunk_semaphore,
                    )
                )
                for idx, chunk_content in enumerate(content_chunks, start=1)
            ]
            logger.info("已创建 %d 个并发chunk任务", len(chunk_tasks))

            chunk_result_map: Dict[int, Dict[str, Any]] = {}
            try:
                for done in asyncio.as_completed(chunk_tasks):
                    chunk_result = await done
                    idx = chunk_result["chunk_index"]
                    chunk_result_map[idx] = chunk_result

                    total_tokens += chunk_result["token_used"]
                    completed_calls += chunk_result["call_count"]

                    partial_chunks = list((extraction_result.raw_result or {}).get("partial_chunks", []))
                    chunk_preview = {
                        "chunk_index": idx,
                        "chunk_total": total_chunks,
                        "fields": self._build_structured_preview_from_chunk(chunk_result["chunk_consensus"]),
                        "records": chunk_result["chunk_consensus"].get("records", []),
                    }
                    partial_chunks.append(chunk_preview)
                    partial_chunks.sort(key=lambda x: x.get("chunk_index", 0))
                    if len(partial_chunks) > 200:
                        partial_chunks = partial_chunks[-200:]

                    processed_chunks = len(chunk_result_map)
                    task.progress_message = f"正在并行分段提取（已完成分片 {processed_chunks}/{total_chunks}）..."
                    extraction_result.raw_result = {
                        "stage": "processing",
                        "total_chunks": total_chunks,
                        "processed_chunks": processed_chunks,
                        "partial_chunks": partial_chunks,
                        "latest_chunk": chunk_preview,
                        "cross_validate_rounds": cross_validate_rounds,
                        "min_agreement": min_agreement,
                        "chunk_concurrency": chunk_concurrency,
                    }
                    extraction_result.structured_result = chunk_preview["fields"]
                    
                    # 【改进】每个chunk完成后立即持久化结果，支持前端实时流式显示
                    await self.db.flush()
                    await self.db.commit()
                    
                    # 诊断日志：记录chunk完成
                    logger.info(
                        "Chunk完成 task_id=%s chunk_idx=%s/%s fields=%d tokens=%s progress=%d%%",
                        task_id,
                        processed_chunks,
                        total_chunks,
                        len(chunk_preview["fields"]),
                        chunk_result["token_used"],
                        40 + int((completed_calls / total_calls) * 40),
                    )
                    
                    await self._checkpoint_progress(
                        task,
                        40.0 + (completed_calls / total_calls) * 40.0,
                        task.progress_message,
                    )
            except Exception:
                for t in chunk_tasks:
                    if not t.done():
                        t.cancel()
                raise

            for idx in range(1, total_chunks + 1):
                chunk_info = chunk_result_map[idx]
                chunk_round_parsed.append(chunk_info["round_results"])
                parsed_chunks.append(chunk_info["chunk_consensus"])

            task.token_used = total_tokens

            parsed = self._merge_chunk_parsed_results(
                parsed_chunks,
                [f.name for f in template.fields],
            )
            field_names = [f.name for f in template.fields]
            parsed = self._finalize_merged_result(parsed, field_names)

            # 纠偏：若聚合结果实质为空，则用强化提示再做一次全量提取。
            if self._is_effectively_empty_result(parsed, field_names):
                await self._log(task_id, "warning", "extraction_empty_retry", "检测到提取结果为空，触发强化提示重试")
                retry_document_content = (
                    f"{document_content}\n\n"
                    "[质量纠偏指令]\n"
                    "上一轮结果过空。请再次提取，优先输出文档中明确可定位的字段值；"
                    "仅当文档确实不存在对应信息时才返回 null。"
                )
                retry_messages = self.prompt_engine.build_extraction_messages(
                    document_content=retry_document_content,
                    template_fields=fields_data,
                    system_prompt=template.system_prompt,
                    extraction_prompt_template=template.extraction_prompt_template,
                    few_shot_examples=template.few_shot_examples,
                )
                retry_response = await adapter.chat(retry_messages, llm_config)
                total_tokens += retry_response.total_tokens or 0

                logger.info(
                    "llm_retry_output task_id=%s model=%s tokens=%s content=%s",
                    task_id,
                    llm_config.model,
                    retry_response.total_tokens,
                    self._truncate_log_text(retry_response.content),
                )

                retry_parsed = self.prompt_engine.parse_llm_response(retry_response.content)
                merged_retry = self._merge_chunk_parsed_results([parsed, retry_parsed], field_names)
                parsed = self._finalize_merged_result(merged_retry, field_names)

            extracted_fields = parsed.get("fields", {})
            records = parsed.get("records", [])
            records = records if isinstance(records, list) else []

            # 保存字段级结果
            structured_result = {}
            total_confidence = 0.0
            valid_count = 0
            for field_def in template.fields:
                field_val = extracted_fields.get(field_def.name, {})
                record_values = []
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    if field_def.name not in record:
                        continue
                    value = record.get(field_def.name)
                    if value is None or value == "":
                        continue
                    record_values.append(value)

                raw_value = field_val.get("value")
                if record_values:
                    raw_value = record_values if len(record_values) > 1 else record_values[0]

                confidence = float(field_val.get("confidence", 0.0))
                source_text = field_val.get("source_text", "")

                normalized_value = self._normalize_value(raw_value, field_def.field_type)
                validate_value = normalized_value[0] if isinstance(normalized_value, list) and normalized_value else normalized_value
                is_valid, validation_error = self._validate_value(
                    validate_value, field_def.required, field_def.validation_rules
                )

                row_preview_value = normalized_value
                if isinstance(normalized_value, list):
                    row_preview_value = normalized_value[0] if normalized_value else None
                if isinstance(row_preview_value, dict):
                    row_preview_value = json.dumps(row_preview_value, ensure_ascii=False)

                ef = ExtractionField(
                    id=str(uuid.uuid4()),
                    task_id=task_id,
                    field_id=field_def.id,
                    field_name=field_def.name,
                    raw_value=str(raw_value) if raw_value is not None else None,
                    normalized_value=str(row_preview_value) if row_preview_value is not None else None,
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
            await self._checkpoint_progress(task, 90.0, "正在保存提取结果...")

            # 保存汇总结果
            extraction_result.raw_result = {
                "stage": "completed",
                "chunk_rounds": chunk_round_parsed,
                "chunks": parsed_chunks,
                "merged": parsed,
                "cross_validate_rounds": cross_validate_rounds,
                "min_agreement": min_agreement,
            }
            extraction_result.structured_result = structured_result
            extraction_result.overall_confidence = overall_confidence

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
            if task.progress < 95:
                task.progress = max(task.progress, 1.0)
            task.progress_message = "提取失败"
            await self._log(task_id, "error", "extraction_failed", str(e))

        await self.db.flush()
        await self.db.commit()
        return task

    async def _extract_single_chunk_with_cross_validation(
        self,
        task_id: str,
        chunk_index: int,
        total_chunks: int,
        chunk_content: str,
        adapter,
        llm_config,
        template,
        fields_data: List[Dict[str, Any]],
        field_names: List[str],
        cross_validate_rounds: int,
        min_agreement: int,
        semaphore: asyncio.Semaphore,
    ) -> Dict[str, Any]:
        """异步执行单个切片的多轮抽取与一致性合并。"""
        async with semaphore:
            logger.info(
                "开始处理Chunk task_id=%s chunk=%d/%d content_len=%d",
                task_id,
                chunk_index,
                total_chunks,
                len(chunk_content),
            )
            if total_chunks > 1:
                chunk_content = (
                    f"[文档切片 {chunk_index}/{total_chunks}]\n"
                    "请仅基于当前切片提取，系统会自动合并所有切片结果。\n\n"
                    f"{chunk_content}"
                )

            round_results: List[Dict[str, Any]] = []
            token_used = 0

            for round_idx in range(1, cross_validate_rounds + 1):
                round_prompt_content = (
                    f"{chunk_content}\n\n"
                    f"[交叉验证轮次 {round_idx}/{cross_validate_rounds}]"
                )
                messages = self.prompt_engine.build_extraction_messages(
                    document_content=round_prompt_content,
                    template_fields=fields_data,
                    system_prompt=template.system_prompt,
                    extraction_prompt_template=template.extraction_prompt_template,
                    few_shot_examples=template.few_shot_examples,
                )

                logger.info(
                    "llm_input task_id=%s chunk=%s/%s round=%s/%s model=%s messages=%s",
                    task_id,
                    chunk_index,
                    total_chunks,
                    round_idx,
                    cross_validate_rounds,
                    llm_config.model,
                    self._truncate_log_text(messages),
                )

                llm_response = await adapter.chat(messages, llm_config)
                logger.info(
                    "llm_output task_id=%s chunk=%s/%s round=%s/%s model=%s tokens=%s content=%s",
                    task_id,
                    chunk_index,
                    total_chunks,
                    round_idx,
                    cross_validate_rounds,
                    llm_config.model,
                    llm_response.total_tokens,
                    self._truncate_log_text(llm_response.content),
                )

                token_used += llm_response.total_tokens or 0
                parsed_round = self.prompt_engine.parse_llm_response(llm_response.content)
                round_results.append(parsed_round)

            chunk_consensus = self._consensus_chunk_parsed_results(
                round_results,
                field_names,
                min_agreement,
            )

            return {
                "chunk_index": chunk_index,
                "round_results": round_results,
                "chunk_consensus": chunk_consensus,
                "token_used": token_used,
                "call_count": cross_validate_rounds,
            }

    def _split_text_with_overlap(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """将长文本按固定窗口切片，并保留重叠区域减少漏提。"""
        if not text:
            return [""]
        if chunk_size <= 0:
            return [text]

        overlap = max(0, min(overlap, chunk_size - 1))
        chunks: List[str] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunks.append(text[start:end])
            if end >= text_len:
                break
            start = end - overlap

        return chunks

    def _merge_chunk_parsed_results(self, parsed_chunks: List[Dict[str, Any]], field_names: List[str]) -> Dict[str, Any]:
        """合并多切片抽取结果：聚合 fields，并去重合并 records。"""
        merged_records: List[Dict[str, Any]] = []
        seen_records = set()
        field_values: Dict[str, List[Any]] = {name: [] for name in field_names}
        field_confidence: Dict[str, float] = {name: 0.0 for name in field_names}
        field_source: Dict[str, str] = {name: "" for name in field_names}

        for parsed in parsed_chunks:
            if not isinstance(parsed, dict):
                continue

            records = parsed.get("records", [])
            if isinstance(records, list):
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    normalized_record = {k: record.get(k) for k in field_names}
                    rec_key = self._stable_dump(normalized_record)
                    if rec_key in seen_records:
                        continue
                    seen_records.add(rec_key)
                    merged_records.append(normalized_record)
                    for field_name in field_names:
                        value = normalized_record.get(field_name)
                        self._append_unique_value(field_values[field_name], value)

            fields = parsed.get("fields", {})
            if not isinstance(fields, dict):
                continue

            for field_name in field_names:
                field_obj = fields.get(field_name, {})
                if not isinstance(field_obj, dict):
                    continue

                value = field_obj.get("value")
                if isinstance(value, list):
                    for item in value:
                        self._append_unique_value(field_values[field_name], item)
                else:
                    self._append_unique_value(field_values[field_name], value)

                confidence = field_obj.get("confidence", 0.0)
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.0
                field_confidence[field_name] = max(field_confidence[field_name], confidence)

                source_text = str(field_obj.get("source_text") or "")
                if len(source_text) > len(field_source[field_name]):
                    field_source[field_name] = source_text

        merged_fields = {}
        for field_name in field_names:
            values = field_values[field_name]
            if len(values) == 0:
                merged_value = None
            elif len(values) == 1:
                merged_value = values[0]
            else:
                merged_value = values

            merged_fields[field_name] = {
                "value": merged_value,
                "confidence": field_confidence[field_name],
                "source_text": field_source[field_name],
            }

        notes = [
            str(p.get("extraction_notes", ""))
            for p in parsed_chunks
            if isinstance(p, dict) and p.get("extraction_notes")
        ]

        return {
            "fields": merged_fields,
            "records": merged_records,
            "extraction_notes": " | ".join(notes[:5]),
        }

    def _consensus_chunk_parsed_results(
        self,
        parsed_rounds: List[Dict[str, Any]],
        field_names: List[str],
        min_agreement: int,
    ) -> Dict[str, Any]:
        """对同一切片多轮抽取做交叉验证，输出一致性结果。"""
        record_votes: Dict[str, Dict[str, Any]] = {}
        field_candidates: Dict[str, Dict[str, int]] = {name: {} for name in field_names}
        field_candidate_values: Dict[str, Dict[str, Any]] = {name: {} for name in field_names}
        field_confidences: Dict[str, List[float]] = {name: [] for name in field_names}
        field_sources: Dict[str, str] = {name: "" for name in field_names}

        for parsed in parsed_rounds:
            if not isinstance(parsed, dict):
                continue

            fields = parsed.get("fields", {})
            if isinstance(fields, dict):
                for field_name in field_names:
                    field_obj = fields.get(field_name, {})
                    if not isinstance(field_obj, dict):
                        continue

                    value = field_obj.get("value")
                    if isinstance(value, list):
                        for item in value:
                            if item is None or item == "":
                                continue
                            item_key = self._stable_dump(item)
                            field_candidates[field_name][item_key] = field_candidates[field_name].get(item_key, 0) + 1
                            field_candidate_values[field_name][item_key] = item
                    elif value is not None and value != "":
                        value_key = self._stable_dump(value)
                        field_candidates[field_name][value_key] = field_candidates[field_name].get(value_key, 0) + 1
                        field_candidate_values[field_name][value_key] = value

                    confidence = field_obj.get("confidence", 0.0)
                    try:
                        confidence = float(confidence)
                    except (TypeError, ValueError):
                        confidence = 0.0
                    if confidence > 0:
                        field_confidences[field_name].append(confidence)

                    source_text = str(field_obj.get("source_text") or "")
                    if len(source_text) > len(field_sources[field_name]):
                        field_sources[field_name] = source_text

            records = parsed.get("records", [])
            if not isinstance(records, list):
                continue

            for record in records:
                if not isinstance(record, dict):
                    continue
                normalized_record = {k: record.get(k) for k in field_names}
                rec_key = self._stable_dump(normalized_record)
                if rec_key not in record_votes:
                    record_votes[rec_key] = {"count": 0, "record": normalized_record}
                record_votes[rec_key]["count"] += 1

        agreed_records = [
            v["record"]
            for v in sorted(record_votes.values(), key=lambda x: x["count"], reverse=True)
            if v["count"] >= min_agreement
        ]

        if not agreed_records:
            fallback = sorted(record_votes.values(), key=lambda x: x["count"], reverse=True)
            agreed_records = [x["record"] for x in fallback[:1]]

        merged_fields: Dict[str, Dict[str, Any]] = {}
        for field_name in field_names:
            values_from_records: List[Any] = []
            for record in agreed_records:
                self._append_unique_value(values_from_records, record.get(field_name))

            voted_values = [
                field_candidate_values[field_name][k]
                for k, c in sorted(field_candidates[field_name].items(), key=lambda x: x[1], reverse=True)
                if c >= min_agreement
            ]

            chosen_values = values_from_records if values_from_records else voted_values
            if len(chosen_values) == 0:
                merged_value = None
            elif len(chosen_values) == 1:
                merged_value = chosen_values[0]
            else:
                merged_value = chosen_values

            conf_list = field_confidences[field_name]
            avg_conf = sum(conf_list) / len(conf_list) if conf_list else 0.0

            merged_fields[field_name] = {
                "value": merged_value,
                "confidence": round(avg_conf, 4),
                "source_text": field_sources[field_name],
            }

        return {
            "fields": merged_fields,
            "records": agreed_records,
            "extraction_notes": f"cross_validate_rounds={len(parsed_rounds)}, min_agreement={min_agreement}",
        }

    def _stable_dump(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except TypeError:
            return str(value)

    def _append_unique_value(self, values: List[Any], value: Any):
        if value is None or value == "":
            return
        value_key = self._stable_dump(value)
        existing = {self._stable_dump(v) for v in values}
        if value_key not in existing:
            values.append(value)

    def _is_effectively_empty_result(self, parsed: Dict[str, Any], field_names: List[str]) -> bool:
        """判断结果是否实质为空：fields 与 records 都没有有效值。"""
        if not isinstance(parsed, dict):
            return True

        fields = parsed.get("fields", {})
        if isinstance(fields, dict):
            for field_name in field_names:
                field_obj = fields.get(field_name, {})
                if not isinstance(field_obj, dict):
                    continue
                value = field_obj.get("value")
                if isinstance(value, list):
                    if any(v not in (None, "") for v in value):
                        return False
                elif value not in (None, ""):
                    return False

        records = parsed.get("records", [])
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict):
                    continue
                for field_name in field_names:
                    if record.get(field_name) not in (None, ""):
                        return False

        return True

    def _normalize_value(self, value: Any, field_type) -> Any:
        """标准化字段值"""
        if value is None:
            return None
        if isinstance(value, (list, dict)):
            return value
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
            select(ExtractionTask)
            .options(
                selectinload(ExtractionTask.document),
                selectinload(ExtractionTask.template),
                selectinload(ExtractionTask.results),
                selectinload(ExtractionTask.field_results),
            )
            .where(ExtractionTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise NotFoundException("提取任务", task_id)

        status_changed = self._sync_task_status_from_celery(task)
        self._mark_task_stale_failed(task)
        if task.status != TaskStatus.FAILED and status_changed:
            task.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.commit()

        self._normalize_task_progress(task)
        return task

    async def restart_failed_task(self, task_id: str) -> ExtractionTask:
        task = await self.get_task_by_id(task_id)
        if task.status != TaskStatus.FAILED:
            raise ValidationException("仅失败任务可重启")

        # 重启前清理历史执行痕迹，避免前端展示旧结果。
        await self.db.execute(delete(ExtractionResult).where(ExtractionResult.task_id == task.id))
        await self.db.execute(delete(ExtractionField).where(ExtractionField.task_id == task.id))
        await self.db.execute(delete(ExtractionLog).where(ExtractionLog.task_id == task.id))

        task.status = TaskStatus.RETRYING
        task.progress = 0.0
        task.progress_message = "任务重启中"
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        task.token_used = None
        task.processing_time_ms = None
        task.retry_count = (task.retry_count or 0) + 1

        if task.document and self._is_excel_document(task.document):
            task.celery_task_id = None
            task.status = TaskStatus.PROCESSING
            task.progress_message = "Excel任务重启执行中"
            await self.db.flush()
            await self.db.commit()
            await self.execute_extraction(task.id)
        else:
            try:
                from app.tasks.extraction_tasks import run_extraction_task
                celery_task = run_extraction_task.apply_async(
                    args=[task.id],
                    queue="extraction",
                    priority=self._priority_to_int(task.priority),
                )
                task.celery_task_id = celery_task.id
                task.status = TaskStatus.QUEUED
                task.progress_message = "任务已重新入队"
            except Exception:
                task.status = TaskStatus.PENDING
                task.progress_message = "队列不可用，任务待调度"

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(task, attribute_names=["created_at", "updated_at", "results", "field_results"])
        return task

    async def delete_failed_task(self, task_id: str):
        await self.delete_task(task_id)

    async def delete_task(self, task_id: str) -> str:
        task = await self.get_task_by_id(task_id)
        cancellable_statuses = {
            TaskStatus.PENDING,
            TaskStatus.QUEUED,
        }
        deletable_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }

        if task.status in cancellable_statuses:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc)
            task.progress = max(float(task.progress or 0.0), 1.0)
            task.progress_message = "任务已取消"
            if not task.error_message:
                task.error_message = "task cancelled by user"
            await self.db.flush()
            await self.db.commit()
            return "cancelled"

        if task.status not in deletable_statuses:
            raise ValidationException("仅待处理/排队中任务可取消，或已完成/失败/已取消任务可删除")

        await self.db.delete(task)
        await self.db.flush()
        await self.db.commit()
        return "deleted"

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
        tasks = result.scalars().all()
        need_commit = False
        for task in tasks:
            if self._sync_task_status_from_celery(task):
                need_commit = True
            before_status = task.status
            self._mark_task_stale_failed(task)
            if task.status != before_status:
                need_commit = True
            self._normalize_task_progress(task)

        if need_commit:
            await self.db.flush()
            await self.db.commit()

        return tasks, total

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

    async def export_results(self, task_ids: List[str], export_format: str) -> Dict[str, str]:
        """导出提取结果，每条记录单独一行。返回对象键和后端下载 URL。"""
        # 收集所有任务的structured_result
        task_results = []
        for task_id in task_ids:
            result_query = await self.db.execute(
                select(ExtractionResult).where(ExtractionResult.task_id == task_id)
            )
            er = result_query.scalar_one_or_none()
            if er and er.structured_result:
                task_results.append(er.structured_result)

        # 转置结构：field->values[] 转换为 row[] 其中每个row是一条记录
        export_rows = []
        for sr in task_results:
            if not sr:
                continue

            # 确定每个字段的值列表
            field_values = {}
            max_rows = 0
            for field_name, field_value in sr.items():
                if isinstance(field_value, list):
                    field_values[field_name] = field_value
                    max_rows = max(max_rows, len(field_value))
                else:
                    field_values[field_name] = [field_value]

            # 生成行数据：每一行包含每个字段的一个值
            max_rows = max(max_rows, 1)
            for row_idx in range(max_rows):
                row_data = {}
                for field_name, values in field_values.items():
                    row_data[field_name] = values[row_idx] if row_idx < len(values) else None
                export_rows.append(row_data)

        if export_format == "json":
            content = json.dumps(export_rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            content_type = "application/json"
            ext = "json"
        else:
            # 默认 xlsx
            import openpyxl, io
            wb = openpyxl.Workbook()
            ws = wb.active
            if export_rows:
                ws.append(list(export_rows[0].keys()))
                for row in export_rows:
                    ws.append([str(v) if v is not None else "" for v in row.values()])
            buf = io.BytesIO()
            wb.save(buf)
            content = buf.getvalue()
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ext = "xlsx"

        export_key = storage.build_result_key(f"export_{uuid.uuid4().hex[:8]}", ext)
        storage.upload_bytes(settings.STORAGE_BUCKET_RESULTS, export_key, content, content_type)
        download_url = f"{settings.API_PREFIX}/extractions/exports/download?object_key={quote(export_key, safe='')}"
        return {
            "object_key": export_key,
            "download_url": download_url,
        }

    def get_export_file(self, object_key: str) -> Tuple[bytes, str, str]:
        """读取导出文件内容，供后端代理下载。"""
        key = (object_key or "").strip().lstrip("/")
        if not key.startswith("results/") or ".." in key:
            raise ValidationException("非法导出文件路径")

        if not storage.file_exists(settings.STORAGE_BUCKET_RESULTS, key):
            raise NotFoundException("导出文件", key)

        content = storage.download_file(settings.STORAGE_BUCKET_RESULTS, key)
        ext = key.rsplit(".", 1)[-1].lower() if "." in key else "bin"
        content_type_map = {
            "json": "application/json",
            "csv": "text/csv",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
        }
        content_type = content_type_map.get(ext, "application/octet-stream")
        filename = f"extraction_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        return content, content_type, filename
