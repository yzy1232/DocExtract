"""
处理器工厂 - 根据文件 MIME 类型选择合适的处理器
"""
from typing import Optional
from app.processors.base_processor import BaseDocumentProcessor
from app.processors.pdf_processor import PDFProcessor
from app.processors.docx_processor import DocxProcessor, ExcelProcessor, TextProcessor
from app.processors.mime_resolver import normalize_mime_type


_PROCESSOR_REGISTRY: dict[str, BaseDocumentProcessor] = {}


def _build_registry() -> dict[str, BaseDocumentProcessor]:
    processors = [
        PDFProcessor(),
        DocxProcessor(),
        ExcelProcessor(),
        TextProcessor(),
    ]
    registry = {}
    for processor in processors:
        for mime in processor.supported_mime_types:
            registry[mime] = processor
    return registry


def get_processor(mime_type: str) -> Optional[BaseDocumentProcessor]:
    """根据 MIME 类型获取对应处理器"""
    global _PROCESSOR_REGISTRY
    if not _PROCESSOR_REGISTRY:
        _PROCESSOR_REGISTRY = _build_registry()
    normalized_mime = normalize_mime_type(mime_type, filename="")
    return _PROCESSOR_REGISTRY.get(normalized_mime)


def is_supported_type(mime_type: str) -> bool:
    """检查是否支持该 MIME 类型"""
    return get_processor(mime_type) is not None


def get_document_format(mime_type: str, filename: str = "") -> str:
    """根据 MIME 类型返回文档格式字符串"""
    normalized_mime = normalize_mime_type(mime_type, filename=filename)
    mapping = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "text/plain": "txt",
        "text/markdown": "txt",
        "text/x-markdown": "txt",
        "application/octet-stream": "txt",
        "image/jpeg": "image",
        "image/png": "image",
        "image/tiff": "image",
        "image/bmp": "image",
    }
    return mapping.get(normalized_mime, "txt")


def suggest_tags(mime_type: str, filename: str = "") -> list[str]:
    """根据文档类型生成标签。"""
    doc_format = get_document_format(mime_type, filename=filename)
    return [f"format:{doc_format}"]
