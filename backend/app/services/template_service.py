"""
模板服务 - 模板 CRUD、版本管理、提示词生成
"""
import uuid
import json
import re
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, delete
from sqlalchemy.orm import selectinload
from app.models.template import Template, TemplateField, TemplateVersion, TemplateCategory, TemplateStatus, FieldType
from app.models.document import Document, DocumentStatus
from app.models.system import LLMConfig as LLMConfigModel, SystemConfig
from app.schemas.template import TemplateCreate, TemplateUpdate, TemplateCategoryCreate
from app.core.exceptions import NotFoundException, ValidationException
from app.llm.base_adapter import LLMMessage
from app.llm.factory import get_default_adapter, get_default_llm_config, create_adapter_from_db_config
from app.core.storage import storage
from app.processors.factory import get_processor
from app.processors.mime_resolver import normalize_mime_type


class TemplateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _resolve_infer_adapter_and_config(self):
        """模板自动提取优先使用系统默认 LLM 配置，回退到环境默认。"""
        llm_config = get_default_llm_config()

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
                    llm_config.model = cfg.model_name or llm_config.model
                    adapter = create_adapter_from_db_config(
                        cfg.api_key_encrypted,
                        cfg.base_url,
                        provider=cfg.provider,
                        model=llm_config.model,
                    )
                    return adapter, llm_config
        except Exception:
            pass

        return get_default_adapter(), llm_config

    async def create(self, data: TemplateCreate, creator_id: str) -> Template:
        """创建模板"""
        template = Template(
            id=str(uuid.uuid4()),
            name=data.name,
            description=data.description,
            category_id=data.category_id,
            creator_id=creator_id,
            is_public=data.is_public,
            tags=data.tags,
            document_types=data.document_types,
            system_prompt=data.system_prompt,
            extraction_prompt_template=data.extraction_prompt_template,
            few_shot_examples=data.few_shot_examples,
            status=data.status or TemplateStatus.DRAFT,
            current_version=1,
        )
        self.db.add(template)
        await self.db.flush()

        # 创建字段
        for idx, field_data in enumerate(data.fields):
            field = TemplateField(
                id=str(uuid.uuid4()),
                template_id=template.id,
                name=field_data.name,
                display_name=field_data.display_name,
                field_type=field_data.field_type,
                description=field_data.description,
                required=field_data.required,
                default_value=field_data.default_value,
                validation_rules=field_data.validation_rules,
                extraction_hints=field_data.extraction_hints,
                region_config=field_data.region_config,
                sort_order=field_data.sort_order or idx,
            )
            self.db.add(field)

        await self.db.flush()
        await self._save_version(template, "初始版本", creator_id)
        return template

    async def get_by_id(self, template_id: str) -> Template:
        # 显式预加载 fields，避免在序列化到 Pydantic 时触发延迟加载失败或字段为空
        result = await self.db.execute(
            select(Template).options(selectinload(Template.fields)).where(Template.id == template_id)
        )
        template = result.scalar_one_or_none()
        if not template:
            raise NotFoundException("模板", template_id)
        return template

    async def update(self, template: Template, data: TemplateUpdate, updater_id: str) -> Template:
        """更新模板（自动保存新版本）"""
        update_fields = data.model_dump(exclude_none=True, exclude={"change_description"})

        # 如果提交了 fields，则先处理字段替换（删除旧字段并新增）
        fields_data = update_fields.pop("fields", None)

        for field, value in update_fields.items():
            setattr(template, field, value)

        if fields_data is not None:
            # 删除已有字段
            await self.db.execute(delete(TemplateField).where(TemplateField.template_id == template.id))
            # 添加新字段
            for idx, field_data in enumerate(fields_data):
                # fields_data 是来自 pydantic.model_dump() 的 dict 列表，使用 dict 取值
                field = TemplateField(
                    id=str(uuid.uuid4()),
                    template_id=template.id,
                    name=field_data.get('name'),
                    display_name=field_data.get('display_name'),
                    field_type=field_data.get('field_type'),
                    description=field_data.get('description'),
                    required=field_data.get('required', False),
                    default_value=field_data.get('default_value'),
                    validation_rules=field_data.get('validation_rules') or {},
                    extraction_hints=field_data.get('extraction_hints'),
                    region_config=field_data.get('region_config') or {},
                    parent_field_id=field_data.get('parent_field_id'),
                    sort_order=field_data.get('sort_order', idx),
                )
                self.db.add(field)

        template.current_version += 1
        await self.db.flush()
        await self._save_version(template, data.change_description or "更新", updater_id)
        return template

    async def delete(self, template: Template):
        """软删除（归档）"""
        template.status = TemplateStatus.ARCHIVED
        await self.db.flush()

    async def list_templates(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        category_id: Optional[str] = None,
        status: Optional[TemplateStatus] = None,
        is_public: Optional[bool] = None,
        creator_id: Optional[str] = None,
    ) -> Tuple[List[Template], int]:
        query = select(Template).where(Template.status != TemplateStatus.ARCHIVED)

        if keyword:
            query = query.where(
                or_(
                    Template.name.ilike(f"%{keyword}%"),
                    Template.description.ilike(f"%{keyword}%"),
                )
            )
        if category_id:
            query = query.where(Template.category_id == category_id)
        if status:
            query = query.where(Template.status == status)
        if is_public is not None:
            query = query.where(Template.is_public == is_public)
        if creator_id:
            query = query.where(Template.creator_id == creator_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()

        query = query.order_by(Template.updated_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        return result.scalars().all(), total

    async def add_field(self, template: Template, field_data, updater_id: str) -> TemplateField:
        """向模板添加字段"""
        field = TemplateField(
            id=str(uuid.uuid4()),
            template_id=template.id,
            **field_data.model_dump(),
        )
        self.db.add(field)
        template.current_version += 1
        await self.db.flush()
        await self._save_version(template, f"添加字段: {field_data.display_name}", updater_id)
        return field

    async def _save_version(self, template: Template, description: str, creator_id: str):
        """保存当前版本快照

        为避免在非异步上下文触发 SQLAlchemy 的懒加载（从而导致 MissingGreenlet 错误），
        在这里显式在异步会话中重新查询并使用 `selectinload` 预加载 `fields` 关系。
        """
        # 在异步上下文中显式加载 fields，避免懒加载在后续同步上下文触发
        result = await self.db.execute(
            select(Template).options(selectinload(Template.fields)).where(Template.id == template.id)
        )
        tpl = result.scalar_one()
        snapshot = {
            "name": tpl.name,
            "description": tpl.description,
            "system_prompt": tpl.system_prompt,
            "extraction_prompt_template": tpl.extraction_prompt_template,
            "few_shot_examples": tpl.few_shot_examples,
            "fields": [
                {
                    "name": f.name,
                    "display_name": f.display_name,
                    "field_type": f.field_type.value if hasattr(f.field_type, 'value') else f.field_type,
                    "description": f.description,
                    "required": f.required,
                    "validation_rules": f.validation_rules,
                    "extraction_hints": f.extraction_hints,
                }
                for f in tpl.fields
            ],
        }
        version = TemplateVersion(
            id=str(uuid.uuid4()),
            template_id=template.id,
            version=template.current_version,
            template_snapshot=snapshot,
            change_description=description,
            created_by=creator_id,
        )
        self.db.add(version)

    # =====================
    # 模板分类管理
    # =====================
    async def create_category(self, data: TemplateCategoryCreate) -> TemplateCategory:
        category = TemplateCategory(
            id=str(uuid.uuid4()),
            name=data.name,
            description=data.description,
            parent_id=data.parent_id,
            sort_order=data.sort_order,
        )
        self.db.add(category)
        await self.db.flush()
        return category

    async def list_categories(self) -> List[TemplateCategory]:
        result = await self.db.execute(
            select(TemplateCategory).order_by(TemplateCategory.sort_order)
        )
        return result.scalars().all()

    async def infer_template_from_document(
        self,
        document_id: str,
        requester_id: str,
        requester_is_superuser: bool,
        template_name: Optional[str] = None,
        description: Optional[str] = None,
        max_fields: int = 20,
    ) -> Dict[str, Any]:
        query = select(Document).where(
            Document.id == document_id,
            Document.deleted_at.is_(None),
        )
        if not requester_is_superuser:
            query = query.where(Document.owner_id == requester_id)

        result = await self.db.execute(query)
        document = result.scalar_one_or_none()
        if not document:
            raise NotFoundException("文档", document_id)
        if document.status != DocumentStatus.PROCESSED:
            raise ValidationException(f"文档尚未解析完成，当前状态: {document.status.value}")

        file_content = storage.download_file(document.storage_bucket, document.storage_path)
        mime_type = normalize_mime_type(document.mime_type, document.name)
        processor = get_processor(mime_type)
        if not processor:
            raise ValidationException(f"文档不支持解析，MIME={mime_type}")

        parse_result = await processor.parse(file_content, document.name)
        full_text = (parse_result.full_text or "").strip()
        if not full_text:
            raise ValidationException("文档内容为空，无法自动生成模板")

        sample_text = full_text[:12000]
        inferred_fields: List[Dict[str, Any]] = []
        inferred_name = (template_name or "").strip() or self._default_template_name(document.name)
        inferred_desc = (description or "").strip() or f"基于文档《{document.display_name or document.name}》自动生成"

        # Excel 优先使用真实表头做确定性推断，避免LLM异常时退化为固定兜底字段。
        is_excel_doc = mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if is_excel_doc:
            excel_fields = self._infer_fields_from_excel_tables(parse_result, max_fields)
            if excel_fields:
                return {
                    "name": inferred_name,
                    "description": inferred_desc,
                    "fields": excel_fields,
                }

        try:
            adapter, llm_config = await self._resolve_infer_adapter_and_config()
            llm_config.temperature = 0.1
            llm_config.max_tokens = min(llm_config.max_tokens, 1800)

            prompt = self._build_infer_prompt(sample_text, inferred_name, inferred_desc, max_fields)
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "你是资深文档结构化工程师。请根据文档内容设计信息提取模板字段。"
                        "输出必须是严格 JSON，不要包含代码块标记或额外解释。"
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ]

            response = await adapter.chat(messages, llm_config)
            parsed = self._parse_infer_response(response.content)
            inferred_name = (parsed.get("name") or inferred_name).strip() or inferred_name
            inferred_desc = (parsed.get("description") or inferred_desc).strip() or inferred_desc
            inferred_fields = parsed.get("fields") or []

            # 第二轮校验：让模型基于文档内容修正字段定义，减少幻觉字段。
            verify_prompt = self._build_verify_prompt(sample_text, inferred_name, inferred_desc, inferred_fields, max_fields)
            verify_messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "你是资深信息抽取QA工程师。请严格检查字段定义是否能从文档稳定提取，"
                        "输出必须是严格 JSON。"
                    ),
                ),
                LLMMessage(role="user", content=verify_prompt),
            ]
            verify_response = await adapter.chat(verify_messages, llm_config)
            verified = self._parse_infer_response(verify_response.content)
            inferred_fields = verified.get("fields") or inferred_fields
        except Exception:
            inferred_fields = self._fallback_fields_from_text(sample_text, max_fields)

        cleaned_fields = self._sanitize_inferred_fields(inferred_fields, max_fields)
        if not cleaned_fields:
            cleaned_fields = self._fallback_fields_from_text(sample_text, max_fields)

        return {
            "name": inferred_name,
            "description": inferred_desc,
            "fields": cleaned_fields,
        }

    def _default_template_name(self, filename: str) -> str:
        base = (filename or "未命名文档").rsplit(".", 1)[0].strip()
        return f"{base}提取模板"

    def _build_infer_prompt(self, doc_text: str, template_name: str, description: str, max_fields: int) -> str:
        allowed_types = ", ".join([t.value for t in FieldType])
        return (
            "请从以下文档内容设计一个可用于结构化提取的模板。\n"
            f"目标模板名: {template_name}\n"
            f"模板描述: {description}\n"
            f"最多输出字段数: {max_fields}\n"
            f"字段类型只能使用: {allowed_types}\n\n"
            "输出格式必须是以下 JSON 对象:\n"
            "{\n"
            "  \"name\": \"模板名称\",\n"
            "  \"description\": \"模板描述\",\n"
            "  \"fields\": [\n"
            "    {\n"
            "      \"name\": \"english_or_zh_key\",\n"
            "      \"display_name\": \"字段显示名\",\n"
            "      \"field_type\": \"text\",\n"
            "      \"description\": \"字段含义\",\n"
            "      \"required\": false,\n"
            "      \"extraction_hints\": \"提取提示\"\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "要求:\n"
            "1) 字段名必须可读且唯一。\n"
            "2) 只输出文档中可能稳定出现的关键字段。\n"
            "3) 不要输出任何 JSON 之外内容。\n\n"
            "文档内容如下:\n"
            f"{doc_text}"
        )

    def _build_verify_prompt(
        self,
        doc_text: str,
        template_name: str,
        description: str,
        fields: List[Dict[str, Any]],
        max_fields: int,
    ) -> str:
        allowed_types = ", ".join([t.value for t in FieldType])
        return (
            "请对以下模板字段进行准确性校验，并输出修正后的字段列表。\n"
            "校验要求:\n"
            "1) 删除无法从文档稳定提取的字段；\n"
            "2) 修正字段类型与字段名；\n"
            "3) 字段名必须唯一且可读；\n"
            f"4) 最多保留 {max_fields} 个字段；\n"
            f"5) 字段类型只能使用: {allowed_types}。\n\n"
            f"模板名: {template_name}\n"
            f"模板描述: {description}\n"
            f"候选字段: {json.dumps(fields, ensure_ascii=False)}\n\n"
            "输出 JSON 格式:\n"
            "{\n"
            "  \"name\": \"模板名称\",\n"
            "  \"description\": \"模板描述\",\n"
            "  \"fields\": [\n"
            "    {\n"
            "      \"name\": \"field_key\",\n"
            "      \"display_name\": \"字段显示名\",\n"
            "      \"field_type\": \"text\",\n"
            "      \"description\": \"字段含义\",\n"
            "      \"required\": false,\n"
            "      \"extraction_hints\": \"提取提示\"\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "文档内容如下:\n"
            f"{doc_text}"
        )

    def _parse_infer_response(self, content: str) -> Dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise ValidationException("LLM 返回内容无法解析为 JSON")
            return json.loads(match.group(0))

    def _sanitize_inferred_fields(self, fields: List[Dict[str, Any]], max_fields: int) -> List[Dict[str, Any]]:
        used_names = set()
        cleaned = []
        for idx, raw in enumerate(fields[:max_fields]):
            if not isinstance(raw, dict):
                continue

            name = self._normalize_field_name(raw.get("name"), idx + 1)
            name = self._deduplicate_name(name, used_names)
            used_names.add(name)

            display_name = str(raw.get("display_name") or raw.get("name") or f"字段{idx + 1}").strip()
            field_type = self._normalize_field_type(raw.get("field_type"))

            cleaned.append(
                {
                    "name": name,
                    "display_name": display_name[:128],
                    "field_type": field_type,
                    "description": (str(raw.get("description") or "").strip() or None),
                    "required": bool(raw.get("required", False)),
                    "extraction_hints": (str(raw.get("extraction_hints") or "").strip() or None),
                    "sort_order": idx,
                }
            )
        return cleaned

    def _normalize_field_name(self, value: Any, idx: int) -> str:
        text = str(value or "").strip()
        if not text:
            return f"field_{idx}"

        text = re.sub(r"\s+", "_", text)
        text = re.sub(r"[^\u4e00-\u9fff_a-zA-Z0-9]", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        if not text:
            return f"field_{idx}"
        if re.match(r"^[0-9]", text):
            text = f"field_{text}"
        return text[:64]

    def _deduplicate_name(self, name: str, used_names: set[str]) -> str:
        if name not in used_names:
            return name
        suffix = 2
        while f"{name}_{suffix}" in used_names:
            suffix += 1
        return f"{name}_{suffix}"[:64]

    def _normalize_field_type(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        alias = {
            "integer": "number",
            "float": "number",
            "double": "number",
            "money": "number",
            "amount": "number",
            "time": "datetime",
            "bool": "boolean",
            "array": "list",
            "object": "custom",
        }
        normalized = alias.get(raw, raw)
        if normalized in {t.value for t in FieldType}:
            return normalized
        return FieldType.TEXT.value

    def _fallback_fields_from_text(self, text: str, max_fields: int) -> List[Dict[str, Any]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        candidate_names = []
        for line in lines[:300]:
            if "：" in line:
                key = line.split("：", 1)[0].strip()
            elif ":" in line:
                key = line.split(":", 1)[0].strip()
            else:
                continue
            if 1 <= len(key) <= 20:
                candidate_names.append(key)

        unique = []
        seen = set()
        for name in candidate_names:
            if name in seen:
                continue
            seen.add(name)
            unique.append(name)
            if len(unique) >= max_fields:
                break

        if not unique:
            unique = ["编号", "名称", "日期", "金额"][:max_fields]

        fields = []
        used_names = set()
        for idx, display_name in enumerate(unique):
            key = self._deduplicate_name(self._normalize_field_name(display_name, idx + 1), used_names)
            used_names.add(key)
            field_type = FieldType.NUMBER.value if any(k in display_name for k in ["金额", "数量", "总计"]) else FieldType.TEXT.value
            if any(k in display_name for k in ["日期", "时间"]):
                field_type = FieldType.DATE.value
            fields.append(
                {
                    "name": key,
                    "display_name": display_name,
                    "field_type": field_type,
                    "description": f"从文档中提取{display_name}",
                    "required": False,
                    "extraction_hints": None,
                    "sort_order": idx,
                }
            )
        return fields

    def _infer_fields_from_excel_tables(self, parse_result, max_fields: int) -> List[Dict[str, Any]]:
        """从 Excel 解析结果中直接提取表头并推断字段类型。"""
        if max_fields <= 0:
            return []

        header_samples: List[Tuple[str, List[Any]]] = []
        seen_headers = set()

        for page in parse_result.pages or []:
            table = (page.tables or [None])[0]
            if not isinstance(table, dict):
                continue

            headers = table.get("headers") if isinstance(table.get("headers"), list) else []
            rows = table.get("rows") if isinstance(table.get("rows"), list) else []
            if not headers:
                continue

            col_count = max(len(headers), max((len(r) for r in rows), default=0))
            for col_idx in range(col_count):
                raw_header = headers[col_idx] if col_idx < len(headers) else ""
                header = str(raw_header).strip() if raw_header is not None else ""
                if not header:
                    continue

                # 跳过明显占位字段名
                if re.match(r"^column_\d+$", header, flags=re.IGNORECASE):
                    continue

                header_key = header.lower()
                if header_key in seen_headers:
                    continue
                seen_headers.add(header_key)

                samples = []
                for row in rows[:60]:
                    if not isinstance(row, list) or col_idx >= len(row):
                        continue
                    value = row[col_idx]
                    if value in (None, ""):
                        continue
                    samples.append(value)

                header_samples.append((header, samples))
                if len(header_samples) >= max_fields:
                    break

            if len(header_samples) >= max_fields:
                break

        if not header_samples:
            return []

        fields: List[Dict[str, Any]] = []
        used_names = set()
        for idx, (display_name, samples) in enumerate(header_samples):
            key = self._deduplicate_name(self._normalize_field_name(display_name, idx + 1), used_names)
            used_names.add(key)
            field_type = self._infer_field_type_from_header_and_samples(display_name, samples)

            fields.append(
                {
                    "name": key,
                    "display_name": display_name[:128],
                    "field_type": field_type,
                    "description": f"从Excel表头提取{display_name}",
                    "required": False,
                    "extraction_hints": None,
                    "sort_order": idx,
                }
            )

        return fields

    def _infer_field_type_from_header_and_samples(self, header: str, samples: List[Any]) -> str:
        """基于表头语义和样本值推断字段类型。"""
        header_l = (header or "").strip().lower()

        if any(k in header_l for k in ["date", "time", "日期", "时间"]):
            return FieldType.DATE.value
        if any(k in header_l for k in ["amount", "price", "total", "qty", "count", "num", "金额", "价格", "数量", "总计"]):
            return FieldType.NUMBER.value

        non_empty = [str(v).strip() for v in samples if v not in (None, "")]
        if not non_empty:
            return FieldType.TEXT.value

        num_count = 0
        date_count = 0
        for v in non_empty:
            if re.match(r"^-?\d+(\.\d+)?$", v.replace(",", "")):
                num_count += 1
            if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", v):
                date_count += 1

        total = len(non_empty)
        if date_count / total >= 0.6:
            return FieldType.DATE.value
        if num_count / total >= 0.7:
            return FieldType.NUMBER.value
        return FieldType.TEXT.value
