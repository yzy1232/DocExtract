"""
提示词工程模块 - 根据模板定义生成结构化提取提示词
"""
import json
from typing import List, Dict, Any, Optional
from app.llm.base_adapter import LLMMessage


# 系统提示词模板
SYSTEM_PROMPT = """你是一个专业的文档信息提取助手。
你的任务是从用户提供的文档内容中，精确提取指定字段的信息。

提取原则：
1. 严格按照字段定义提取，不要推断或杜撰不存在的信息
2. 如果某个字段的信息在文档中不存在，返回 null
3. 对于日期、金额等格式化字段，进行标准化处理
4. 输出必须是合法的 JSON 格式
5. 对每个字段给出置信度评分（0-1之间）
"""

# 提取任务提示词模板
EXTRACTION_PROMPT_TEMPLATE = """请从以下文档内容中提取所需字段信息。

## 文档内容
{document_content}

## 需要提取的字段
{fields_description}

## 输出格式
请严格按照以下 JSON 格式输出，不要包含任何额外说明：
```json
{{
  "fields": {{
    {field_json_template}
  }},
  "extraction_notes": "提取过程的备注说明（如有特殊情况）"
}}
```

其中每个字段的格式为：
```json
"字段名": {{
  "value": "提取到的值（未找到则为null）",
  "confidence": 0.95,
  "source_text": "来源原文片段"
}}
```
"""

FEW_SHOT_EXAMPLE_TEMPLATE = """
## 示例
{examples}
"""


class PromptEngine:
    """提示词构建引擎"""

    def build_extraction_messages(
        self,
        document_content: str,
        template_fields: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        extraction_prompt_template: Optional[str] = None,
        few_shot_examples: Optional[List[Dict[str, Any]]] = None,
        max_content_length: int = 8000,
    ) -> List[LLMMessage]:
        """
        构建提取任务的完整消息列表。

        Args:
            document_content: 文档文本内容
            template_fields: 模板字段定义列表
            system_prompt: 自定义系统提示词（优先于默认值）
            extraction_prompt_template: 自定义提取提示词模板
            few_shot_examples: Few-shot 示例列表
            max_content_length: 文档内容最大字符数（超出则截断）
        """
        messages: List[LLMMessage] = []

        # 1. 系统提示词
        messages.append(LLMMessage(
            role="system",
            content=system_prompt or SYSTEM_PROMPT,
        ))

        # 2. Few-shot 示例（如有）
        if few_shot_examples:
            for example in few_shot_examples[:3]:  # 最多3个示例
                messages.append(LLMMessage(role="user", content=example.get("input", "")))
                messages.append(LLMMessage(role="assistant", content=example.get("output", "")))

        # 3. 构建用户提取请求
        # 截断过长文档
        if len(document_content) > max_content_length:
            document_content = document_content[:max_content_length] + "\n\n[内容因长度限制已截断...]"

        fields_desc = self._build_fields_description(template_fields)
        field_json_template = self._build_field_json_template(template_fields)

        prompt_template = extraction_prompt_template or EXTRACTION_PROMPT_TEMPLATE
        user_prompt = prompt_template.format(
            document_content=document_content,
            fields_description=fields_desc,
            field_json_template=field_json_template,
        )

        messages.append(LLMMessage(role="user", content=user_prompt))
        return messages

    def _build_fields_description(self, fields: List[Dict[str, Any]]) -> str:
        """生成字段描述文本"""
        lines = []
        for f in fields:
            parts = [f"- **{f['display_name']}** (`{f['name']}`)"]
            parts.append(f"  类型: {f.get('field_type', 'text')}")
            if f.get("description"):
                parts.append(f"  说明: {f['description']}")
            if f.get("required"):
                parts.append("  必填: 是")
            if f.get("extraction_hints"):
                parts.append(f"  提取提示: {f['extraction_hints']}")
            if f.get("validation_rules"):
                rules = f["validation_rules"]
                if rules.get("pattern"):
                    parts.append(f"  格式要求: {rules['pattern']}")
            lines.append("\n".join(parts))
        return "\n\n".join(lines)

    def _build_field_json_template(self, fields: List[Dict[str, Any]]) -> str:
        """生成 JSON 模板示例"""
        entries = []
        for f in fields:
            entries.append(
                f'    "{f["name"]}": {{"value": null, "confidence": 0.0, "source_text": ""}}'
            )
        return ",\n".join(entries)

    def parse_llm_response(self, response_text: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的 JSON 文本。
        兼容 markdown 代码块包裹的情况。
        """
        import re
        # 提取 JSON 代码块
        json_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
        match = json_pattern.search(response_text)
        if match:
            json_str = match.group(1)
        else:
            # 尝试直接解析
            json_str = response_text.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试修复常见 JSON 错误（如末尾多余逗号）
            json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                return {"parse_error": str(e), "raw_text": response_text}
