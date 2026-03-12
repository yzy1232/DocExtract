"""
文档处理器基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class PageContent:
    """单页解析结果"""
    page_number: int
    raw_text: str
    tables: List[Dict[str, Any]] = field(default_factory=list)   # [{headers, rows}]
    images: List[Dict[str, Any]] = field(default_factory=list)   # [{caption, alt_text}]
    has_table: bool = False
    has_image: bool = False
    is_scanned: bool = False
    confidence: Optional[float] = None  # OCR 置信度


@dataclass
class DocumentParseResult:
    """文档解析完整结果"""
    page_count: int
    pages: List[PageContent]
    full_text: str                              # 所有页文本合并
    language: Optional[str] = None
    encoding: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    has_ocr: bool = False
    errors: List[str] = field(default_factory=list)


class BaseDocumentProcessor(ABC):
    """文档处理器抽象基类"""

    @property
    @abstractmethod
    def supported_mime_types(self) -> List[str]:
        """此处理器支持的 MIME 类型列表"""
        ...

    @abstractmethod
    async def parse(self, file_content: bytes, filename: str) -> DocumentParseResult:
        """解析文档，提取文本和结构化内容"""
        ...

    def _detect_language(self, text: str) -> str:
        """简单语言检测：中文/英文"""
        if not text:
            return "unknown"
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        ratio = chinese_chars / max(len(text), 1)
        return "zh" if ratio > 0.1 else "en"

    def _clean_text(self, text: str) -> str:
        """基础文本清洗"""
        import re
        # 去除多余空白行（保留段落结构）
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 去除行首行尾空白
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(lines).strip()
