"""
模板服务 - 模板 CRUD、版本管理、提示词生成
"""
import uuid
import json
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, delete
from sqlalchemy.orm import selectinload
from app.models.template import Template, TemplateField, TemplateVersion, TemplateCategory, TemplateStatus
from app.schemas.template import TemplateCreate, TemplateUpdate, TemplateCategoryCreate
from app.core.exceptions import NotFoundException, ForbiddenException, ConflictException


class TemplateService:
    def __init__(self, db: AsyncSession):
        self.db = db

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
            status=TemplateStatus.DRAFT,
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
