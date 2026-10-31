import io
import os
import uuid
from pathlib import Path
from typing import List, Union, Dict, Tuple, Optional
from pydantic import BaseModel, Field
from PIL import Image
import pymupdf as fitz
import pytesseract

from app.pipeline_services.ocr.exceptions import (
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)
from app.pipeline_services.ocr.document_loader import (
    DocumentLoader,
    ValidatedDocument,
    load_and_validate_document,
)
from app.pipeline_services.ocr.pdf_inspector import PDFInspector, PDFInspectionResult
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.telemetry.attributes import (
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_VERSION,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    PIPELINE_NAME_VAL,
    PIPELINE_VERSION_VAL,
    EXECUTION_ID,
    EXECUTION_ENTITY_ID,
    STAGE_NAME,
    STAGE_VERSION,
    STAGE_STATUS,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    ERROR_TYPE,
    ERROR_MESSAGE,
)

tracer = trace.get_tracer("enterprise_pipeline.ocr")

_tesseract_cmd = os.getenv("TESSERACT_CMD")
if _tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd


class BoundingBox(BaseModel):
    """
    Normalized bounding box coordinates in document points or pixels.
    """
    x0: float = Field(..., description="Left coordinate")
    y0: float = Field(..., description="Top coordinate")
    x1: float = Field(..., description="Right coordinate")
    y1: float = Field(..., description="Bottom coordinate")


class EvidenceWord(BaseModel):
    """
    Word-level OCR evidence including text, confidence, and bounding box.
    """
    text: str = Field(..., description="Word text string")
    confidence: Union[float, None] = Field(default=None, description="OCR confidence score (0-100), or None if native text")
    bounding_box: Union[BoundingBox, None] = Field(default=None, description="Bounding box coordinates")


class EvidenceLine(BaseModel):
    """
    Line-level OCR evidence grouping constituent words.
    """
    text: str = Field(..., description="Line text string")
    confidence: Union[float, None] = Field(default=None, description="Average line confidence score (0-100), or None")
    bounding_box: Union[BoundingBox, None] = Field(default=None, description="Bounding box envelope enclosing line words")
    words: List[EvidenceWord] = Field(default_factory=list, description="Constituent word-level evidence items")


class EvidencePage(BaseModel):
    """
    Page-level OCR evidence containing page dimensions, raw text, and structured line/word layout evidence.
    """
    page_number: int = Field(..., description="1-based page index")
    width: Union[float, None] = Field(default=None, description="Page width in points/pixels")
    height: Union[float, None] = Field(default=None, description="Page height in points/pixels")
    raw_text: str = Field(..., description="Full raw un-segmented page text")
    lines: List[EvidenceLine] = Field(default_factory=list, description="Structured line-level evidence")
    status: str = Field(default="DIRECT_TEXT", description="Page extraction status: DIRECT_TEXT or OCR_REQUIRED")


class DetailedOCREvidenceResult(BaseModel):
    """
    Complete normalized OCR evidence extraction result for a document.
    """
    engine: str = Field(..., description="OCR engine used ('pymupdf' or 'tesseract')")
    file_name: str = Field(..., description="Base filename of the document")
    total_pages: int = Field(..., description="Total page count")
    pages: List[EvidencePage] = Field(default_factory=list, description="Per-page OCR evidence records")


class OCREvidenceExtractor:
    """
    Production-grade Detailed OCR Evidence Extractor.

    Extracts word-level bounding boxes, line groupings, confidence scores,
    and page dimensions for both digital PDFs (via PyMuPDF) and scanned documents/images (via Tesseract).
    """

    ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

    def __init__(self):
        self.inspector = PDFInspector()

    def _verify_tesseract_installed(self) -> None:
        """Verifies Tesseract availability."""
        try:
            pytesseract.get_tesseract_version()
        except (pytesseract.TesseractNotFoundError, FileNotFoundError) as err:
            raise DocumentProcessingError(
                "Tesseract OCR executable is not installed or not found on system PATH."
            ) from err
        except Exception as err:
            if "TesseractNotFoundError" in type(err).__name__:
                raise DocumentProcessingError(
                    "Tesseract OCR executable is not installed or not found on system PATH."
                ) from err
            pass

    def extract_evidence(
        self,
        document: Union[ValidatedDocument, str, Path],
        claim_id: Optional[Union[int, str]] = None,
        execution_id: Optional[str] = None,
    ) -> DetailedOCREvidenceResult:
        """
        Extracts detailed OCR evidence from a document.

        Args:
            document: ValidatedDocument instance or path string/Path to a document.
            claim_id: Optional claim ID.
            execution_id: Optional execution ID.

        Returns:
            DetailedOCREvidenceResult: Structured evidence result with bounding boxes and confidence.
        """
        if isinstance(document, (str, Path)):
            validated_doc = load_and_validate_document(document)
        elif isinstance(document, ValidatedDocument):
            validated_doc = document
        else:
            raise DocumentProcessingError(
                f"Invalid document input type: {type(document).__name__}. "
                f"Expected ValidatedDocument, str, or Path."
            )

        ext = validated_doc.extension.lower()

        if ext == ".pdf":
            # Inspect PDF to check if digital embedded text is present
            inspection = self.inspector.inspect(validated_doc, claim_id=claim_id, execution_id=execution_id)
            if inspection.has_embedded_text:
                return self._extract_pymupdf_evidence(validated_doc, inspection, claim_id=claim_id, execution_id=execution_id)
            else:
                self._verify_tesseract_installed()
                return self._extract_tesseract_pdf_evidence(validated_doc, inspection, claim_id=claim_id, execution_id=execution_id)
        elif ext in self.ALLOWED_IMAGE_EXTENSIONS:
            self._verify_tesseract_installed()
            return self._extract_tesseract_image_evidence(validated_doc, claim_id=claim_id, execution_id=execution_id)
        else:
            raise UnsupportedDocumentTypeError(
                f"OCREvidenceExtractor does not support extension '{ext}'."
            )

    def _resolve_context(
        self,
        claim_id: Optional[Union[int, str]],
        execution_id: Optional[str],
        default_doc_ref: str,
    ) -> Tuple[Union[int, str], str, List[str], List[str]]:
        curr_claim_id = claim_id
        curr_exec_id = execution_id
        if not curr_claim_id or not curr_exec_id:
            curr_span = trace.get_current_span()
            if curr_span and hasattr(curr_span, "attributes") and curr_span.attributes:
                curr_claim_id = curr_claim_id or curr_span.attributes.get("claim_id") or curr_span.attributes.get("execution.entity_id")
                curr_exec_id = curr_exec_id or curr_span.attributes.get("execution.id")
        curr_claim_id = curr_claim_id or 1
        curr_exec_id = curr_exec_id or f"EXEC-{uuid.uuid4().hex[:12].upper()}"
        input_artifacts = [f"doc_{default_doc_ref}"]
        output_artifacts = [f"art_ocr_{default_doc_ref}"]
        return curr_claim_id, curr_exec_id, input_artifacts, output_artifacts

    def _extract_pymupdf_evidence(
        self,
        validated_doc: ValidatedDocument,
        inspection: PDFInspectionResult,
        claim_id: Optional[Union[int, str]] = None,
        execution_id: Optional[str] = None,
    ) -> DetailedOCREvidenceResult:
        """Extracts word and line evidence for digital PDFs using PyMuPDF."""
        c_id, exec_id, in_arts, out_arts = self._resolve_context(claim_id, execution_id, validated_doc.file_name)
        with tracer.start_as_current_span("pymupdf_text_extraction") as extract_span:
            extract_span.set_attribute("claim_id", c_id)
            extract_span.set_attribute(EXECUTION_ID, exec_id)
            extract_span.set_attribute(EXECUTION_ENTITY_ID, str(c_id))
            extract_span.set_attribute(PIPELINE_NAME, PIPELINE_NAME_VAL)
            extract_span.set_attribute(PIPELINE_VERSION, PIPELINE_VERSION_VAL)
            extract_span.set_attribute(STAGE_NAME, "pymupdf_text_extraction")
            extract_span.set_attribute(STAGE_VERSION, "1.0.0")
            extract_span.set_attribute(INPUT_ARTIFACT_IDS, in_arts)
            extract_span.set_attribute(OUTPUT_ARTIFACT_IDS, out_arts)
            extract_span.set_attribute("extraction.method", "pymupdf")
            extract_span.set_attribute("extraction.page_count", inspection.total_pages)

            try:
                try:
                    file_bytes = validated_doc.file_path.read_bytes()
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                except Exception as err:
                    raise DocumentProcessingError(
                        f"Corrupt or invalid PDF file '{validated_doc.file_name}': {str(err)}"
                    ) from err

                try:
                    pages_evidence: List[EvidencePage] = []
                    total_text_length = 0

                    for page_idx in range(inspection.total_pages):
                        page_num = page_idx + 1
                        with tracer.start_as_current_span(f"ocr_page_{page_num}") as page_span:
                            page = doc[page_idx]
                            raw_text = page.get_text().strip()
                            total_text_length += len(raw_text)
                            page_w = round(page.rect.width, 2)
                            page_h = round(page.rect.height, 2)

                            has_meaningful = len(raw_text) > 0 and any(c.isalnum() for c in raw_text)
                            page_status = "DIRECT_TEXT" if has_meaningful else "OCR_REQUIRED"

                            page_span.set_attribute("page_number", page_num)
                            page_span.set_attribute("extraction_method", page_status)
                            page_span.set_attribute("character_count", len(raw_text))

                            if not has_meaningful:
                                # Page lacks direct text -> marked OCR_REQUIRED, page layout metadata retained
                                page_span.set_attribute("word_count", 0)
                                page_span.set_attribute("status", "OCR_REQUIRED")
                                page_span.set_status(Status(StatusCode.OK))
                                pages_evidence.append(
                                    EvidencePage(
                                        page_number=page_num,
                                        width=page_w,
                                        height=page_h,
                                        raw_text="",
                                        lines=[],
                                        status="OCR_REQUIRED",
                                    )
                                )
                                continue

                            # Extract words: (x0, y0, x1, y1, word_text, block_no, line_no, word_no)
                            words_data = page.get_text("words")
                            line_groups: Dict[Tuple[int, int], List[Tuple[float, float, float, float, str]]] = {}

                            for w in words_data:
                                x0, y0, x1, y1, word_text = float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]).strip()
                                block_no, line_no = int(w[5]), int(w[6])
                                if not word_text:
                                    continue
                                key = (block_no, line_no)
                                if key not in line_groups:
                                    line_groups[key] = []
                                line_groups[key].append((x0, y0, x1, y1, word_text))

                            lines: List[EvidenceLine] = []

                            for key, word_list in line_groups.items():
                                evidence_words: List[EvidenceWord] = []
                                for w in word_list:
                                    bbox = BoundingBox(
                                        x0=round(w[0], 2),
                                        y0=round(w[1], 2),
                                        x1=round(w[2], 2),
                                        y1=round(w[3], 2),
                                    )
                                    evidence_words.append(
                                        EvidenceWord(
                                            text=w[4],
                                            confidence=None,  # PyMuPDF does not provide OCR confidence
                                            bounding_box=bbox,
                                        )
                                    )

                                if not evidence_words:
                                    continue

                                line_str = " ".join(w.text for w in evidence_words)
                                min_x0 = min(w.bounding_box.x0 for w in evidence_words)
                                min_y0 = min(w.bounding_box.y0 for w in evidence_words)
                                max_x1 = max(w.bounding_box.x1 for w in evidence_words)
                                max_y1 = max(w.bounding_box.y1 for w in evidence_words)

                                line_bbox = BoundingBox(x0=min_x0, y0=min_y0, x1=max_x1, y1=max_y1)

                                lines.append(
                                    EvidenceLine(
                                        text=line_str,
                                        confidence=None,
                                        bounding_box=line_bbox,
                                        words=evidence_words,
                                    )
                                )

                            # Fallback if words was empty but raw_text exists
                            if not lines and raw_text:
                                for l_str in raw_text.splitlines():
                                    if l_str.strip():
                                        lines.append(EvidenceLine(text=l_str.strip(), confidence=None, bounding_box=None, words=[]))

                            total_words = sum(len(line.words) for line in lines) if lines else len(raw_text.split())
                            page_span.set_attribute("word_count", total_words)
                            page_span.set_attribute("status", "DIRECT_TEXT")
                            page_span.set_status(Status(StatusCode.OK))

                            pages_evidence.append(
                                EvidencePage(
                                    page_number=page_num,
                                    width=page_w,
                                    height=page_h,
                                    raw_text=raw_text,
                                    lines=lines,
                                    status="DIRECT_TEXT",
                                )
                            )

                    extract_span.set_attribute("extraction.text_length", total_text_length)
                    extract_span.set_attribute(STAGE_STATUS, "completed")
                    extract_span.set_status(Status(StatusCode.OK))

                    return DetailedOCREvidenceResult(
                        engine="pymupdf",
                        file_name=validated_doc.file_name,
                        total_pages=inspection.total_pages,
                        pages=pages_evidence,
                    )
                finally:
                    doc.close()
            except Exception as err:
                extract_span.record_exception(err)
                extract_span.set_status(Status(StatusCode.ERROR, str(err)))
                extract_span.set_attribute(STAGE_STATUS, "failed")
                extract_span.set_attribute("error.type", type(err).__name__)
                extract_span.set_attribute("error.message", str(err))
                raise

    def _extract_tesseract_image_evidence(
        self,
        validated_doc: ValidatedDocument,
        claim_id: Optional[Union[int, str]] = None,
        execution_id: Optional[str] = None,
    ) -> DetailedOCREvidenceResult:
        """Extracts word and line evidence for raster images using Tesseract image_to_data."""
        c_id, exec_id, in_arts, out_arts = self._resolve_context(claim_id, execution_id, validated_doc.file_name)
        with tracer.start_as_current_span("ocr_text_extraction") as ocr_span:
            ocr_span.set_attribute("claim_id", c_id)
            ocr_span.set_attribute(EXECUTION_ID, exec_id)
            ocr_span.set_attribute(EXECUTION_ENTITY_ID, str(c_id))
            ocr_span.set_attribute(PIPELINE_NAME, PIPELINE_NAME_VAL)
            ocr_span.set_attribute(PIPELINE_VERSION, PIPELINE_VERSION_VAL)
            ocr_span.set_attribute(STAGE_NAME, "ocr_text_extraction")
            ocr_span.set_attribute(STAGE_VERSION, "1.0.0")
            ocr_span.set_attribute(INPUT_ARTIFACT_IDS, in_arts)
            ocr_span.set_attribute(OUTPUT_ARTIFACT_IDS, out_arts)
            ocr_span.set_attribute("ocr.engine", "tesseract")
            ocr_span.set_attribute("ocr.language", "eng")
            ocr_span.set_attribute("ocr.page_count", 1)

            try:
                try:
                    file_bytes = validated_doc.file_path.read_bytes()
                    image = Image.open(io.BytesIO(file_bytes))
                    image.verify()
                    image = Image.open(io.BytesIO(file_bytes))
                except Exception as err:
                    raise DocumentProcessingError(
                        f"Corrupt or invalid image file '{validated_doc.file_name}': {str(err)}"
                    ) from err

                page_evidence = self._process_image_with_tesseract(image, page_number=1)
                text_len = len(page_evidence.raw_text or "")
                conf_values = [w.confidence for line in page_evidence.lines for w in line.words if w.confidence is not None]
                avg_conf = round(sum(conf_values) / len(conf_values), 2) if conf_values else 0.0

                ocr_span.set_attribute("ocr.confidence", avg_conf)
                ocr_span.set_attribute("extraction.text_length", text_len)
                ocr_span.set_attribute(STAGE_STATUS, "completed")
                ocr_span.set_status(Status(StatusCode.OK))

                return DetailedOCREvidenceResult(
                    engine="tesseract",
                    file_name=validated_doc.file_name,
                    total_pages=1,
                    pages=[page_evidence],
                )
            except Exception as err:
                ocr_span.record_exception(err)
                ocr_span.set_status(Status(StatusCode.ERROR, str(err)))
                ocr_span.set_attribute(STAGE_STATUS, "failed")
                ocr_span.set_attribute("error.type", type(err).__name__)
                ocr_span.set_attribute("error.message", str(err))
                raise

    def _extract_tesseract_pdf_evidence(
        self,
        validated_doc: ValidatedDocument,
        inspection: PDFInspectionResult,
        claim_id: Optional[Union[int, str]] = None,
        execution_id: Optional[str] = None,
    ) -> DetailedOCREvidenceResult:
        """Extracts word and line evidence for scanned PDFs by rendering pages and processing with Tesseract."""
        c_id, exec_id, in_arts, out_arts = self._resolve_context(claim_id, execution_id, validated_doc.file_name)
        with tracer.start_as_current_span("ocr_text_extraction") as ocr_span:
            ocr_span.set_attribute("claim_id", c_id)
            ocr_span.set_attribute(EXECUTION_ID, exec_id)
            ocr_span.set_attribute(EXECUTION_ENTITY_ID, str(c_id))
            ocr_span.set_attribute(PIPELINE_NAME, PIPELINE_NAME_VAL)
            ocr_span.set_attribute(PIPELINE_VERSION, PIPELINE_VERSION_VAL)
            ocr_span.set_attribute(STAGE_NAME, "ocr_text_extraction")
            ocr_span.set_attribute(STAGE_VERSION, "1.0.0")
            ocr_span.set_attribute(INPUT_ARTIFACT_IDS, in_arts)
            ocr_span.set_attribute(OUTPUT_ARTIFACT_IDS, out_arts)
            ocr_span.set_attribute("ocr.engine", "tesseract")
            ocr_span.set_attribute("ocr.language", "eng")
            ocr_span.set_attribute("ocr.page_count", inspection.total_pages)

            try:
                try:
                    file_bytes = validated_doc.file_path.read_bytes()
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                except Exception as err:
                    raise DocumentProcessingError(
                        f"Corrupt or invalid PDF file '{validated_doc.file_name}': {str(err)}"
                    ) from err

                try:
                    pages_evidence: List[EvidencePage] = []
                    all_conf_values: List[float] = []
                    total_text_length = 0

                    for page_idx in range(inspection.total_pages):
                        page = doc[page_idx]
                        pix = page.get_pixmap(dpi=150)
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        page_evidence = self._process_image_with_tesseract(img, page_number=page_idx + 1)
                        pages_evidence.append(page_evidence)
                        total_text_length += len(page_evidence.raw_text or "")
                        for line in page_evidence.lines:
                            for w in line.words:
                                if w.confidence is not None:
                                    all_conf_values.append(w.confidence)

                    avg_conf = round(sum(all_conf_values) / len(all_conf_values), 2) if all_conf_values else 0.0
                    ocr_span.set_attribute("ocr.confidence", avg_conf)
                    ocr_span.set_attribute("extraction.text_length", total_text_length)
                    ocr_span.set_attribute(STAGE_STATUS, "completed")
                    ocr_span.set_status(Status(StatusCode.OK))

                    return DetailedOCREvidenceResult(
                        engine="tesseract",
                        file_name=validated_doc.file_name,
                        total_pages=inspection.total_pages,
                        pages=pages_evidence,
                    )
                finally:
                    doc.close()
            except Exception as err:
                ocr_span.record_exception(err)
                ocr_span.set_status(Status(StatusCode.ERROR, str(err)))
                ocr_span.set_attribute(STAGE_STATUS, "failed")
                ocr_span.set_attribute("error.type", type(err).__name__)
                ocr_span.set_attribute("error.message", str(err))
                raise

    def _process_image_with_tesseract(self, image: Image.Image, page_number: int) -> EvidencePage:
        """Runs Tesseract image_to_data on a PIL image and returns an EvidencePage."""
        with tracer.start_as_current_span(f"ocr_page_{page_number}") as page_span:
            page_span.set_attribute("page_number", page_number)
            page_span.set_attribute("extraction_method", "TESSERACT_OCR")

            img_w = float(image.width)
            img_h = float(image.height)

            try:
                data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            except Exception as err:
                page_span.record_exception(err)
                page_span.set_status(Status(StatusCode.ERROR, str(err)))
                raise DocumentProcessingError(
                    f"Tesseract OCR evidence extraction failed: {str(err)}"
                ) from err

            n_boxes = len(data.get("text", []))
            line_words_map: Dict[Tuple[int, int, int], List[Dict[str, float | str]]] = {}

            for i in range(n_boxes):
                word_str = str(data["text"][i]).strip()
                conf_val = float(data["conf"][i])
                if not word_str or conf_val < 0:
                    continue

                block_num = int(data["block_num"][i])
                par_num = int(data["par_num"][i])
                line_num = int(data["line_num"][i])
                key = (block_num, par_num, line_num)

                if key not in line_words_map:
                    line_words_map[key] = []

                left = float(data["left"][i])
                top = float(data["top"][i])
                w_w = float(data["width"][i])
                w_h = float(data["height"][i])

                line_words_map[key].append({
                    "text": word_str,
                    "conf": round(conf_val, 2),
                    "x0": round(left, 2),
                    "y0": round(top, 2),
                    "x1": round(left + w_w, 2),
                    "y1": round(top + w_h, 2),
                })

            lines: List[EvidenceLine] = []
            raw_line_texts: List[str] = []

            for key, word_dicts in line_words_map.items():
                words: List[EvidenceWord] = []
                for w in word_dicts:
                    bbox = BoundingBox(
                        x0=float(w["x0"]),
                        y0=float(w["y0"]),
                        x1=float(w["x1"]),
                        y1=float(w["y1"]),
                    )
                    words.append(
                        EvidenceWord(
                            text=str(w["text"]),
                            confidence=float(w["conf"]),
                            bounding_box=bbox,
                        )
                    )

                if not words:
                    continue

                line_str = " ".join(w.text for w in words).strip()
                if not line_str:
                    continue

                raw_line_texts.append(line_str)
                avg_conf = round(sum(w.confidence for w in words) / len(words), 2)
                min_x0 = min(w.bounding_box.x0 for w in words)
                min_y0 = min(w.bounding_box.y0 for w in words)
                max_x1 = max(w.bounding_box.x1 for w in words)
                max_y1 = max(w.bounding_box.y1 for w in words)

                line_bbox = BoundingBox(x0=min_x0, y0=min_y0, x1=max_x1, y1=max_y1)

                lines.append(
                    EvidenceLine(
                        text=line_str,
                        confidence=avg_conf,
                        bounding_box=line_bbox,
                        words=words,
                    )
                )

            raw_text = "\n".join(raw_line_texts)
            if not raw_text:
                try:
                    raw_text = pytesseract.image_to_string(image).strip()
                except Exception:
                    raw_text = ""

            total_words = sum(len(line.words) for line in lines) if lines else len(raw_text.split())
            page_span.set_attribute("character_count", len(raw_text))
            page_span.set_attribute("word_count", total_words)
            page_span.set_attribute("status", "TESSERACT_OCR")
            page_span.set_status(Status(StatusCode.OK))

            return EvidencePage(
                page_number=page_number,
                width=img_w,
                height=img_h,
                raw_text=raw_text,
                lines=lines,
            )


def extract_ocr_evidence(
    document: Union[ValidatedDocument, str, Path],
    claim_id: Optional[Union[int, str]] = None,
    execution_id: Optional[str] = None,
) -> DetailedOCREvidenceResult:
    """
    Convenience function to extract detailed OCR evidence from a document.

    Args:
        document: ValidatedDocument or path to document file.
        claim_id: Optional claim ID.
        execution_id: Optional execution ID.

    Returns:
        DetailedOCREvidenceResult: Extracted evidence details.
    """
    extractor = OCREvidenceExtractor()
    return extractor.extract_evidence(document, claim_id=claim_id, execution_id=execution_id)

