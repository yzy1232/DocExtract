"""
MIME 类型解析与归一化。
用于上传场景下对 application/octet-stream 等不可靠类型做修正。
"""
from __future__ import annotations

import os
from typing import Optional


EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


MIME_ALIASES: dict[str, str] = {
    "application/x-pdf": "application/pdf",
    "application/acrobat": "application/pdf",
    "application/msword": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/x-markdown": "text/markdown",
    "application/octet-stream": "application/octet-stream",
}


def detect_mime_by_filename(filename: str) -> Optional[str]:
    """根据文件名扩展名推断 MIME。"""
    ext = os.path.splitext((filename or "").lower())[1]
    return EXTENSION_TO_MIME.get(ext)


def normalize_mime_type(mime_type: Optional[str], filename: str, default_text: bool = True) -> str:
    """
    归一化 MIME 类型。
    - 优先使用传入 mime_type，并做别名映射
    - 对空值或 application/octet-stream 尝试按扩展名识别
    - 识别失败时默认降级 text/plain（便于按 txt 解析）
    """
    normalized = (mime_type or "").split(";")[0].strip().lower()
    normalized = MIME_ALIASES.get(normalized, normalized)

    if normalized and normalized != "application/octet-stream":
        return normalized

    detected = detect_mime_by_filename(filename)
    if detected:
        return detected

    return "text/plain" if default_text else (normalized or "application/octet-stream")
