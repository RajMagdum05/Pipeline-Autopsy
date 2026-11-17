"""Evidence extraction adapted from the legacy PyMuPDF and Tesseract chain."""
import io
import tempfile
import os
import re
import math
from pathlib import Path
from typing import Any

import pymupdf as fitz
try:
    import pytesseract
except ImportError:  # Native-text PDFs remain processable without the optional OCR runtime.
    pytesseract = None
from PIL import Image
from pydantic import BaseModel, Field

from app.document_processing.document_loader import DocumentLoader, ValidatedDocument
from app.document_processing.exceptions import DocumentProcessingError
from app.document_processing.image_preprocessor import DocumentImagePreprocessor
from app.document_processing.pdf_inspector import PDFInspector, PDFInspectionResult


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class EvidenceWord(BaseModel):
    text: str
    confidence: float | None = None
    bounding_box: BoundingBox | None = None


class EvidenceLine(BaseModel):
    text: str
    confidence: float | None = None
    bounding_box: BoundingBox | None = None
    words: list[EvidenceWord] = Field(default_factory=list)


class EvidencePage(BaseModel):
    page_number: int
    width: float | None = None
    height: float | None = None
    raw_text: str
    lines: list[EvidenceLine] = Field(default_factory=list)
    status: str = "DIRECT_TEXT"
    error: str | None = None


class DetailedOCREvidenceResult(BaseModel):
    engine: str
    file_name: str
    total_pages: int
    pages: list[EvidencePage] = Field(default_factory=list)


class OCREvidenceExtractor:
    ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

    def __init__(self):
        self.inspector = PDFInspector()
        self.loader = DocumentLoader()
        self.preprocessor = DocumentImagePreprocessor()

    def extract_evidence(self, document, claim_id=None, execution_id=None, inspection=None,
                         force_ocr_pages=None, render_dpi=None):
        validated = document if isinstance(document, ValidatedDocument) else self.loader.load_and_validate(document)
        ext = validated.extension.lower()
        if ext == ".pdf":
            inspection = inspection or self.inspector.inspect(validated)
            data = validated.file_path.read_bytes()
            try:
                pdf = fitz.open(stream=data, filetype="pdf")
            except Exception as exc:
                raise DocumentProcessingError(f"Corrupt or invalid PDF file '{validated.file_name}': {exc}") from exc
            try:
                pages = []
                for index, info in enumerate(inspection.pages):
                    page = pdf[index]
                    native = self._pymupdf_page(page, index + 1)
                    # Configurable heuristic: OCR pages with images, weak native text, or
                    # unusually sparse text. This may OCR decorative images; exact duplicate
                    # lines are removed when the two sources are combined.
                    min_chars = int(os.getenv("OCR_NATIVE_MIN_CHARS", "24"))
                    min_words = int(os.getenv("OCR_NATIVE_MIN_WORDS", "4"))
                    native_words = len(native.raw_text.split())
                    has_images = bool(page.get_images(full=True)) or any(
                        block.get("type") == 1 for block in page.get_text("dict").get("blocks", [])
                    )
                    has_drawings = bool(page.get_drawings())
                    if not native.raw_text and not has_images and not has_drawings:
                        native.status = "BLANK"
                        pages.append(native)
                        continue
                    route_ocr = (index + 1 in set(force_ocr_pages or []) or info.status != "DIRECT_TEXT" or has_images or
                                 (has_drawings and len(native.raw_text) < min_chars) or
                                 len(native.raw_text) < min_chars or native_words < min_words)
                    if not route_ocr:
                        pages.append(native)
                        continue
                    try:
                        pix = page.get_pixmap(dpi=int(render_dpi or os.getenv("OCR_RENDER_DPI", "200")))
                        image = Image.open(io.BytesIO(pix.tobytes("png")))
                        ocr = self._ocr_page(image, index + 1)
                    except Exception as exc:
                        pages.append(EvidencePage(page_number=index + 1, width=page.rect.width,
                            height=page.rect.height, raw_text=native.raw_text, lines=native.lines,
                            status="PARTIAL_FAILURE" if native.raw_text else "UNREADABLE",
                            error=f"Page OCR failed ({type(exc).__name__})."))
                        continue
                    if not ocr.raw_text.strip():
                        gray = image.convert("L")
                        histogram = gray.histogram()
                        total_pixels = sum(histogram)
                        near_white = sum(histogram[245:]) / max(total_pixels, 1)
                        ocr.status = "BLANK" if near_white >= 0.995 else "UNREADABLE"
                    if native.raw_text and ocr.raw_text:
                        native_lines = [line for line in native.raw_text.splitlines() if line.strip()]
                        seen = {re.sub(r"\W+", " ", line).strip().casefold() for line in native_lines}
                        extra = [line for line in ocr.raw_text.splitlines()
                                 if line.strip() and re.sub(r"\W+", " ", line).strip().casefold() not in seen]
                        ocr.raw_text = "\n".join(native_lines + extra)
                        ocr.lines = native.lines + [line for line in ocr.lines
                            if re.sub(r"\W+", " ", line.text).strip().casefold() not in seen]
                        ocr.status = "HYBRID"
                        pages.append(ocr)
                    elif native.raw_text and ocr.status == "BLANK":
                        pages.append(native)
                    elif native.raw_text:
                        native.status = "PARTIAL_FAILURE"
                        native.error = "Image-based content was present but OCR returned no usable text."
                        pages.append(native)
                    else:
                        pages.append(ocr)
            finally:
                pdf.close()
            methods = {p.status for p in pages}
            engine = "hybrid" if "HYBRID" in methods or len(methods) > 1 else ("tesseract" if "TESSERACT_OCR" in methods else "pymupdf")
            return DetailedOCREvidenceResult(engine=engine, file_name=validated.file_name, total_pages=len(pages), pages=pages)
        if ext in self.ALLOWED_IMAGE_EXTENSIONS:
            try:
                image = Image.open(validated.file_path)
                image.load()
            except Exception as exc:
                return DetailedOCREvidenceResult(engine="tesseract", file_name=validated.file_name,
                    total_pages=1, pages=[EvidencePage(page_number=1, raw_text="", status="UNREADABLE",
                        error=f"Image OCR failed ({type(exc).__name__}).")])
            return DetailedOCREvidenceResult(engine="tesseract", file_name=validated.file_name, total_pages=1,
                                             pages=[self._ocr_page(image, 1)])
        raise DocumentProcessingError(f"Unsupported document type: {ext}")

    def _pymupdf_page(self, page, number: int) -> EvidencePage:
        text = page.get_text().strip()
        groups: dict[tuple[int, int], list[EvidenceWord]] = {}
        for item in page.get_text("words"):
            x0, y0, x1, y1, word = item[:5]
            if str(word).strip():
                groups.setdefault((int(item[5]), int(item[6])), []).append(EvidenceWord(
                    text=str(word).strip(), bounding_box=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)))
        lines = []
        for words in groups.values():
            lines.append(EvidenceLine(text=" ".join(w.text for w in words), words=words))
        if not lines:
            lines = [EvidenceLine(text=line.strip()) for line in text.splitlines() if line.strip()]
        return EvidencePage(page_number=number, width=page.rect.width, height=page.rect.height,
                            raw_text=text, lines=lines, status="DIRECT_TEXT")

    def _ocr_page(self, image: Image.Image, number: int) -> EvidencePage:
        if pytesseract is None:
            raise DocumentProcessingError("Tesseract OCR Python dependency is not installed.")
        try:
            with tempfile.TemporaryDirectory(prefix="document-processing-") as tmp:
                rendered = Path(tmp) / "rendered.png"
                prepared = Path(tmp) / "preprocessed.png"
                image.save(rendered, format="PNG")
                self.preprocessor.preprocess_rendered_page(rendered, page_number=number, output_path=prepared)
                with Image.open(prepared) as preprocessed:
                    timeout = float(os.getenv("OCR_PAGE_TIMEOUT_SECONDS", "45"))
                    data = pytesseract.image_to_data(preprocessed, output_type=pytesseract.Output.DICT, timeout=timeout)
                    fallback = pytesseract.image_to_string(preprocessed, timeout=timeout).strip()
                    width, height = preprocessed.size
        except Exception as exc:
            raise DocumentProcessingError(f"Tesseract OCR failed: {exc}") from exc
        groups: dict[tuple[int, int, int], list[EvidenceWord]] = {}
        for i, value in enumerate(data.get("text", [])):
            word = str(value).strip()
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                continue
            if not word or not math.isfinite(conf) or conf < 0 or conf > 100:
                continue
            left, top = float(data["left"][i]), float(data["top"][i])
            right, bottom = left + float(data["width"][i]), top + float(data["height"][i])
            key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
            groups.setdefault(key, []).append(EvidenceWord(text=word, confidence=conf,
                bounding_box=BoundingBox(x0=left, y0=top, x1=right, y1=bottom)))
        lines = []
        for words in groups.values():
            text = " ".join(w.text for w in words)
            confs = [w.confidence for w in words if w.confidence is not None]
            boxes = [w.bounding_box for w in words if w.bounding_box]
            bbox = BoundingBox(x0=min(b.x0 for b in boxes), y0=min(b.y0 for b in boxes),
                               x1=max(b.x1 for b in boxes), y1=max(b.y1 for b in boxes)) if boxes else None
            lines.append(EvidenceLine(text=text, confidence=sum(confs) / len(confs) if confs else None,
                                      bounding_box=bbox, words=words))
        text = "\n".join(line.text for line in lines) or fallback
        return EvidencePage(page_number=number, width=width, height=height, raw_text=text,
                            lines=lines, status="TESSERACT_OCR")
