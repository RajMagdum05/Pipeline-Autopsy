"""
DEPRECATED: This module is the legacy monolithic OCR processor.

Use `app.services.ocr` (the clean modular package) instead.

The orchestrator lives at: app.services.ocr.orchestrator.OCRApplicationService
The router now imports from: app.services.ocr

This file is kept for backward compatibility and reference only.
"""

import warnings
warnings.warn(
    "app.services.document_processor is deprecated. Use app.services.ocr instead.",
    DeprecationWarning,
    stacklevel=2,
)

from datetime import datetime, timezone
import io
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, Field
import pymupdf as fitz
import pytesseract
from PIL import Image
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.schemas import OCRWord, OCRLine, OCRPage, OCRResult

tracer = trace.get_tracer("enterprise_pipeline.ocr")


class DocumentProcessingError(Exception):
    """Custom exception raised when document text extraction or processing fails."""
    pass


class BaseOCRProvider:
    """Base interface for OCR and Document Processing providers."""

    def process(self, path: Path, document_id: int | str | None = None) -> OCRResult:
        raise NotImplementedError("Subclasses must implement process()")


class PyMuPDFProvider(BaseOCRProvider):
    """Provider for extracting embedded text and word bounding boxes directly from text-based PDFs."""

    def process(self, path: Path, document_id: int | str | None = None) -> OCRResult:
        start_time = time.time()
        try:
            doc = fitz.open(path)
        except Exception as e:
            raise DocumentProcessingError(f"Corrupt or invalid PDF file: {str(e)}") from e

        try:
            pages: list[OCRPage] = []
            total_char_count = 0

            for page_idx, page in enumerate(doc):
                raw_text = page.get_text().strip()
                if not raw_text:
                    continue

                total_char_count += len(raw_text)
                page_w = round(page.rect.width, 2)
                page_h = round(page.rect.height, 2)

                # Extract words via PyMuPDF (x0, y0, x1, y1, word_text, block_no, line_no, word_no)
                words_data = page.get_text("words")
                line_groups: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}

                for w in words_data:
                    x0, y0, x1, y1, word_text, block_no, line_no = w[0], w[1], w[2], w[3], w[4], w[5], w[6]
                    if not word_text.strip():
                        continue
                    key = (block_no, line_no)
                    if key not in line_groups:
                        line_groups[key] = []
                    line_groups[key].append((x0, y0, x1, y1, word_text.strip()))

                lines: list[OCRLine] = []
                for key, word_list in line_groups.items():
                    words: list[OCRWord] = []
                    l_x0 = min(w[0] for w in word_list)
                    l_y0 = min(w[1] for w in word_list)
                    l_x1 = max(w[2] for w in word_list)
                    l_y1 = max(w[3] for w in word_list)

                    for w in word_list:
                        w_bbox = [round(w[0], 2), round(w[1], 2), round(w[2] - w[0], 2), round(w[3] - w[1], 2)]
                        words.append(OCRWord(text=w[4], confidence=None, bounding_box=w_bbox))

                    line_text = " ".join(w.text for w in words)
                    line_bbox = [round(l_x0, 2), round(l_y0, 2), round(l_x1 - l_x0, 2), round(l_y1 - l_y0, 2)]
                    lines.append(OCRLine(text=line_text, confidence=None, bounding_box=line_bbox, words=words))

                # Fallback line splitting if word data was empty
                if not lines and raw_text:
                    for l_str in raw_text.splitlines():
                        if l_str.strip():
                            lines.append(OCRLine(text=l_str.strip(), confidence=None))

                pages.append(
                    OCRPage(
                        page_number=page_idx + 1,
                        width=page_w,
                        height=page_h,
                        raw_text=raw_text,
                        lines=lines,
                    )
                )

            duration_ms = round((time.time() - start_time) * 1000, 2)
            has_embedded_text = len(pages) > 0 and total_char_count > 0

            if has_embedded_text:
                return OCRResult(
                    document_id=document_id,
                    status="success",
                    engine="pymupdf",
                    engine_version=fitz.__version__,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    processing_duration_ms=duration_ms,
                    processing_metadata={
                        "filename": path.name,
                        "total_pages": len(doc),
                        "total_characters": total_char_count,
                        "is_scanned": False,
                    },
                    pages=pages,
                    errors=[],
                )

            return OCRResult(
                document_id=document_id,
                status="success",
                engine="pymupdf",
                engine_version=fitz.__version__,
                created_at=datetime.now(timezone.utc).isoformat(),
                processing_duration_ms=duration_ms,
                processing_metadata={
                    "filename": path.name,
                    "total_pages": len(doc),
                    "total_characters": 0,
                    "is_scanned": True,
                },
                pages=[],
                errors=[],
            )
        finally:
            doc.close()


def _extract_tesseract_pages_lines_and_words(image: Image.Image, page_num: int = 1) -> OCRPage:
    """Helper to run Tesseract image_to_data and return an OCRPage with lines and words."""
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    n_boxes = len(data.get("text", []))

    line_words_map: dict[tuple[int, int, int], list[dict[str, Any]]] = {}

    for i in range(n_boxes):
        text = str(data["text"][i]).strip()
        conf_val = float(data["conf"][i])
        if not text or conf_val < 0:
            continue

        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        if key not in line_words_map:
            line_words_map[key] = []

        line_words_map[key].append({
            "text": text,
            "conf": conf_val,
            "left": float(data["left"][i]),
            "top": float(data["top"][i]),
            "width": float(data["width"][i]),
            "height": float(data["height"][i]),
        })

    lines: list[OCRLine] = []
    raw_lines: list[str] = []

    for key, word_dicts in line_words_map.items():
        words: list[OCRWord] = []
        for w in word_dicts:
            w_bbox = [w["left"], w["top"], w["width"], w["height"]]
            words.append(OCRWord(text=w["text"], confidence=round(w["conf"], 2), bounding_box=w_bbox))

        line_str = " ".join(w.text for w in words).strip()
        if not line_str:
            continue

        raw_lines.append(line_str)
        avg_conf = round(sum(w.confidence for w in words) / len(words), 2) if words else None
        left = min(w.bounding_box[0] for w in words)
        top = min(w.bounding_box[1] for w in words)
        right = max(w.bounding_box[0] + w.bounding_box[2] for w in words)
        bottom = max(w.bounding_box[1] + w.bounding_box[3] for w in words)
        line_bbox = [left, top, right - left, bottom - top]

        lines.append(OCRLine(text=line_str, confidence=avg_conf, bounding_box=line_bbox, words=words))

    raw_text = "\n".join(raw_lines)
    if not raw_text:
        raw_text = pytesseract.image_to_string(image).strip()
        if raw_text and not lines:
            lines = [OCRLine(text=l_str.strip()) for l_str in raw_text.splitlines() if l_str.strip()]

    return OCRPage(
        page_number=page_num,
        width=float(image.width),
        height=float(image.height),
        raw_text=raw_text,
        lines=lines,
    )


class TesseractProvider(BaseOCRProvider):
    """Provider for OCR processing on image files and scanned PDFs via Tesseract."""

    def process(self, path: Path, document_id: int | str | None = None) -> OCRResult:
        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._process_scanned_pdf(path, document_id)
        else:
            return self._process_image(path, document_id)

    def _process_image(self, path: Path, document_id: int | str | None = None) -> OCRResult:
        start_time = time.time()
        try:
            image = Image.open(path)
        except Exception as e:
            raise DocumentProcessingError(f"Corrupt or invalid image file: {str(e)}") from e

        try:
            page = _extract_tesseract_pages_lines_and_words(image, page_num=1)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            tess_version = pytesseract.get_tesseract_version().public
        except pytesseract.TesseractNotFoundError:
            raise DocumentProcessingError(
                "Tesseract OCR binary not found on system. Please install Tesseract-OCR to process images."
            )
        except Exception as e:
            raise DocumentProcessingError(f"OCR failed for image file: {str(e)}") from e

        return OCRResult(
            document_id=document_id,
            status="success",
            engine="tesseract",
            engine_version=str(tess_version),
            created_at=datetime.now(timezone.utc).isoformat(),
            processing_duration_ms=duration_ms,
            processing_metadata={
                "filename": path.name,
                "total_pages": 1,
                "is_scanned": True,
            },
            pages=[page],
            errors=[],
        )

    def _process_scanned_pdf(self, path: Path, document_id: int | str | None = None) -> OCRResult:
        start_time = time.time()
        try:
            doc = fitz.open(path)
        except Exception as e:
            raise DocumentProcessingError(f"Corrupt or invalid PDF file: {str(e)}") from e

        pages: list[OCRPage] = []
        try:
            for page_idx, page in enumerate(doc):
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_page = _extract_tesseract_pages_lines_and_words(img, page_num=page_idx + 1)
                pages.append(ocr_page)

            duration_ms = round((time.time() - start_time) * 1000, 2)
            tess_version = pytesseract.get_tesseract_version().public

            return OCRResult(
                document_id=document_id,
                status="success",
                engine="tesseract",
                engine_version=str(tess_version),
                created_at=datetime.now(timezone.utc).isoformat(),
                processing_duration_ms=duration_ms,
                processing_metadata={
                    "filename": path.name,
                    "total_pages": len(doc),
                    "is_scanned": True,
                },
                pages=pages,
                errors=[],
            )
        except pytesseract.TesseractNotFoundError:
            raise DocumentProcessingError(
                "Tesseract OCR binary not found on system. Please install Tesseract-OCR to process scanned documents."
            )
        except Exception as e:
            raise DocumentProcessingError(f"OCR failed for PDF file: {str(e)}") from e
        finally:
            doc.close()


def process_document(file_path: str | Path, document_id: int | str | None = None) -> OCRResult:
    """
    Processes a document (PDF, PNG, JPG, JPEG) and returns a structured normalized OCRResult.

    - For text-based PDFs: Uses PyMuPDFProvider. If text is extracted, returns result.
      If scanned PDF (no embedded text), falls back to TesseractProvider.
    - For image files: Uses TesseractProvider.
    - Creates an OpenTelemetry span 'OCR process_document' with performance & diagnostic metadata.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    with tracer.start_as_current_span("OCR process_document") as span:
        if document_id is not None:
            span.set_attribute("document_id", str(document_id))
        span.set_attribute("file_extension", ext)
        span.set_attribute("filename", path.name)

        if not path.exists():
            error_msg = f"File not found: {path}"
            span.set_status(Status(StatusCode.ERROR, error_msg))
            raise DocumentProcessingError(error_msg)

        if ext not in {".pdf", ".png", ".jpg", ".jpeg"}:
            error_msg = f"Unsupported file format '{ext}'. Allowed: .pdf, .png, .jpg, .jpeg"
            span.set_status(Status(StatusCode.ERROR, error_msg))
            raise DocumentProcessingError(error_msg)

        try:
            if ext == ".pdf":
                pymupdf_provider = PyMuPDFProvider()
                result = pymupdf_provider.process(path, document_id=document_id)
                if result.pages and any(p.raw_text.strip() for p in result.pages):
                    _attach_ocr_span_metadata(span, result)
                    return result

                # Scanned PDF fallback to Tesseract
                tesseract_provider = TesseractProvider()
                result = tesseract_provider.process(path, document_id=document_id)
                _attach_ocr_span_metadata(span, result)
                return result
            else:
                tesseract_provider = TesseractProvider()
                result = tesseract_provider.process(path, document_id=document_id)
                _attach_ocr_span_metadata(span, result)
                return result
        except DocumentProcessingError as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        except Exception as e:
            err = DocumentProcessingError(f"Error processing file '{path.name}': {str(e)}")
            span.record_exception(err)
            span.set_status(Status(StatusCode.ERROR, str(err)))
            raise err from e


def _attach_ocr_span_metadata(span: trace.Span, result: OCRResult) -> None:
    """Attaches safe, non-PII OCR performance and diagnostic metadata to the OpenTelemetry span."""
    span.set_attribute("ocr_engine", result.engine)
    if result.engine_version:
        span.set_attribute("ocr_engine_version", result.engine_version)
    span.set_attribute("page_count", len(result.pages))
    span.set_attribute("is_scanned", result.processing_metadata.get("is_scanned", False))
    span.set_attribute("total_characters", result.processing_metadata.get("total_characters", 0))
    span.set_status(Status(StatusCode.OK))


def extract_text_from_document(file_path: str | Path) -> str:
    """
    Backward-compatibility wrapper returning joined raw text string from process_document().
    """
    result = process_document(file_path)
    return "\n\n".join(p.raw_text for p in result.pages if p.raw_text.strip())
