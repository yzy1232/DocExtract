"""
提取服务 - LLM 智能提取任务管理和执行
"""
import uuid
import time
import json
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timezone
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
from app.core.storage import storage
from app.config import settings
from app.processors.mime_resolver import normalize_mime_type


EXTRACTION_CHUNK_SIZE = 7000
EXTRACTION_CHUNK_OVERLAP = 800
EXTRACTION_CROSS_VALIDATE_ROUNDS = 2
EXTRACTION_MIN_AGREEMENT = 2
EXTRACTION_STALE_TIMEOUT_SECONDS = 300


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
        await self.db.flush()
        await self.db.commit()

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

            parsed_chunks = []
            chunk_round_parsed = []
            total_tokens = 0
            total_chunks = len(content_chunks)
            total_calls = max(1, total_chunks * cross_validate_rounds)
            completed_calls = 0
            for idx, chunk_content in enumerate(content_chunks, start=1):
                if total_chunks > 1:
                    chunk_content = (
                        f"[文档切片 {idx}/{total_chunks}]\n"
                        f"请仅基于当前切片提取，系统会自动合并所有切片结果。\n\n"
                        f"{chunk_content}"
                    )

                current_chunk_round_results = []
                for round_idx in range(1, cross_validate_rounds + 1):
                    task.progress_message = (
                        f"正在交叉验证提取（分片 {idx}/{total_chunks}，轮次 {round_idx}/{cross_validate_rounds}）..."
                    )
                    await self.db.flush()

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

                    llm_response = await adapter.chat(messages, llm_config)
                    total_tokens += llm_response.total_tokens or 0
                    parsed_round = self.prompt_engine.parse_llm_response(llm_response.content)
                    current_chunk_round_results.append(parsed_round)

                    completed_calls += 1
                    await self._checkpoint_progress(
                        task,
                        40.0 + (completed_calls / total_calls) * 40.0,
                        task.progress_message,
                    )

                chunk_round_parsed.append(current_chunk_round_results)
                parsed_chunks.append(
                    self._consensus_chunk_parsed_results(
                        current_chunk_round_results,
                        [f.name for f in template.fields],
                        min_agreement,
                    )
                )

            task.token_used = total_tokens

            parsed = self._merge_chunk_parsed_results(
                parsed_chunks,
                [f.name for f in template.fields],
            )
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
            extraction_result = ExtractionResult(
                id=str(uuid.uuid4()),
                task_id=task_id,
                raw_result={
                    "chunk_rounds": chunk_round_parsed,
                    "chunks": parsed_chunks,
                    "merged": parsed,
                    "cross_validate_rounds": cross_validate_rounds,
                    "min_agreement": min_agreement,
                },
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
            if task.progress < 95:
                task.progress = max(task.progress, 1.0)
            task.progress_message = "提取失败"
            await self._log(task_id, "error", "extraction_failed", str(e))

        await self.db.flush()
        await self.db.commit()
        return task

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

        self._mark_task_stale_failed(task)
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
        task = await self.get_task_by_id(task_id)
        if task.status != TaskStatus.FAILED:
            raise ValidationException("仅失败任务可删除")

        await self.db.delete(task)
        await self.db.flush()
        await self.db.commit()

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
