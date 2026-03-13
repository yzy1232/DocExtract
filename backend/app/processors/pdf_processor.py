"""
PDF 文档处理器 - 使用 PyMuPDF (fitz) 解析 PDF
"""
import io
from typing import List
import fitz  # PyMuPDF
from PIL import Image
from app.processors.base_processor import BaseDocumentProcessor, DocumentParseResult, PageContent
from app.config import settings

try:
    import pytesseract
except Exception:
    pytesseract = None


class PDFProcessor(BaseDocumentProcessor):
    """PDF 文档解析器，支持文本型和扫描型 PDF"""

    @property
    def supported_mime_types(self) -> List[str]:
        return ["application/pdf"]

    async def parse(self, file_content: bytes, filename: str) -> DocumentParseResult:
        pages: List[PageContent] = []
        metadata: dict = {}
        has_ocr = False
        errors: List[str] = []

        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
            # 提取文档元数据
            meta = doc.metadata
            metadata = {k: v for k, v in meta.items() if v}

            for page_num in range(len(doc)):
                page = doc[page_num]
                page_content = await self._process_page(page, page_num + 1)
                pages.append(page_content)
                if page_content.is_scanned:
                    has_ocr = True

            doc.close()

        except Exception as e:
            errors.append(f"PDF解析失败: {str(e)}")

        full_text = "\n\n".join(p.raw_text for p in pages if p.raw_text)
        full_text = self._clean_text(full_text)
        language = self._detect_language(full_text[:2000])

        return DocumentParseResult(
            page_count=len(pages),
            pages=pages,
            full_text=full_text,
            language=language,
            metadata=metadata,
            has_ocr=has_ocr,
            errors=errors,
        )

    async def _process_page(self, page: fitz.Page, page_number: int) -> PageContent:
        """处理单个 PDF 页面"""
        # 提取文本
        raw_text = page.get_text("text", sort=True)
        is_scanned = len(raw_text.strip()) < 50

        # 提取表格（使用 PyMuPDF 的表格检测）
        tables = []
        try:
            tab_finder = page.find_tables()
            for tab in tab_finder.tables:
                table_data = tab.extract()
                if table_data:
                    headers = table_data[0] if table_data else []
                    rows = table_data[1:] if len(table_data) > 1 else []
                    tables.append({"headers": headers, "rows": rows})
        except Exception:
            pass

        # 提取图片信息
        images = []
        img_list = page.get_images(full=True)
        for img_info in img_list:
            images.append({"xref": img_info[0], "alt_text": ""})

        text_result = self._clean_text(raw_text)

        # 如果页面被判断为扫描页，尝试基于配置的 OCR 引擎进行 OCR（默认为 tesseract）
        if is_scanned and pytesseract and settings.OCR_ENGINE == "tesseract":
            try:
                pix = page.get_pixmap()
                img_bytes = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_bytes))
                lang = "+".join(settings.OCR_LANGUAGES) if settings.OCR_LANGUAGES else None
                ocr_text = pytesseract.image_to_string(img, lang=lang) if lang else pytesseract.image_to_string(img)
                text_result = self._clean_text(ocr_text)
                confidence = None
                is_scanned = False if text_result else True
            except Exception:
                confidence = None
        else:
            confidence = 1.0 if not is_scanned else None

        return PageContent(
            page_number=page_number,
            raw_text=text_result,
            tables=tables,
            images=images,
            has_table=len(tables) > 0,
            has_image=len(images) > 0,
            is_scanned=is_scanned,
            confidence=confidence,
        )
