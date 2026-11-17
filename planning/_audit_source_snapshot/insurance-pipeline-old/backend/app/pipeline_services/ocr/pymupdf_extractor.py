from pathlib import Path
from typing import List, Union
from pydantic import BaseModel, Field
import pymupdf as fitz

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
from app.pipeline_services.ocr.evidence_extractor import (
    BoundingBox,
    EvidenceWord,
    EvidenceLine,
    EvidencePage,
    DetailedOCREvidenceResult,
)


class ExtractedPageText(BaseModel):
    """
    Extracted text and structural metadata for a single PDF page.
    """
    page_number: int = Field(..., description="1-based page index")
    text: str = Field(..., description="Extracted text content from this page")
    width: float = Field(..., description="Page width in points")
    height: float = Field(..., description="Page height in points")
    status: str = Field(default="DIRECT_TEXT", description="Page extraction status: DIRECT_TEXT or OCR_REQUIRED")
    has_meaningful_text: bool = Field(default=True, description="True if page contains meaningful non-whitespace text")


class DirectTextExtractionResult(BaseModel):
    """
    Structured result of direct PyMuPDF text extraction from a PDF.
    """
    file_name: str = Field(..., description="Base filename of the document")
    total_pages: int = Field(..., description="Total page count")
    has_embedded_text: bool = Field(..., description="True if document contains selectable embedded text")
    requires_ocr: bool = Field(..., description="True if no embedded text was found and OCR engine fallback is needed")
    full_text: str = Field(..., description="Combined text across all pages")
    pages: List[ExtractedPageText] = Field(default_factory=list, description="Per-page extracted text and layout bounds")


class PyMuPDFTextExtractor:
    """
    Production-grade Direct Text Extractor using PyMuPDF.

    Extracts embedded selectable text, page numbers, and page dimensions
    from PDF documents while preserving document structure.
    """

    def __init__(self):
        self.inspector = PDFInspector()

    def extract(self, document: Union[ValidatedDocument, str, Path]) -> DirectTextExtractionResult:
        """
        Extracts embedded text from a PDF document.

        Args:
            document: ValidatedDocument instance or path string/Path to a PDF file.

        Returns:
            DirectTextExtractionResult: Extracted text structured by page and combined document text.

        Raises:
            UnsupportedDocumentTypeError: If the file is not a .pdf.
            DocumentProcessingError: If the PDF is corrupt or unreadable.
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

        if validated_doc.extension.lower() != ".pdf":
            raise UnsupportedDocumentTypeError(
                f"PyMuPDFTextExtractor only processes '.pdf' files, but received '{validated_doc.extension}'"
            )

        # Step 2: Inspect PDF first
        inspection = self.inspector.inspect(validated_doc)

        # Read file bytes for safe in-memory opening
        try:
            file_bytes = validated_doc.file_path.read_bytes()
        except Exception as e:
            raise DocumentProcessingError(
                f"Failed to read file '{validated_doc.file_name}': {str(e)}"
            ) from e

        doc = None
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as e:
            raise DocumentProcessingError(
                f"Corrupt or invalid PDF file '{validated_doc.file_name}': {str(e)}"
            ) from e

        try:
            pages_extracted: List[ExtractedPageText] = []
            page_text_list: List[str] = []

            for page_idx in range(inspection.total_pages):
                page = doc[page_idx]
                raw_text = page.get_text().strip()
                page_w = round(page.rect.width, 2)
                page_h = round(page.rect.height, 2)

                has_meaningful = len(raw_text) > 0 and any(c.isalnum() for c in raw_text)
                page_status = "DIRECT_TEXT" if has_meaningful else "OCR_REQUIRED"

                pages_extracted.append(
                    ExtractedPageText(
                        page_number=page_idx + 1,
                        text=raw_text if has_meaningful else "",
                        width=page_w,
                        height=page_h,
                        status=page_status,
                        has_meaningful_text=has_meaningful,
                    )
                )
                if has_meaningful:
                    page_text_list.append(raw_text)

            full_text = "\n\n".join(page_text_list)
            has_embedded_text = inspection.has_embedded_text
            requires_ocr = inspection.ocr_required

            return DirectTextExtractionResult(
                file_name=validated_doc.file_name,
                total_pages=inspection.total_pages,
                has_embedded_text=has_embedded_text,
                requires_ocr=requires_ocr,
                full_text=full_text,
                pages=pages_extracted,
            )
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    def extract_evidence(
        self, document: Union[ValidatedDocument, str, Path]
    ) -> DetailedOCREvidenceResult:
        """
        Extracts detailed page-by-page word and line layout evidence for digital PDFs using PyMuPDF.

        Args:
            document: ValidatedDocument instance or path string/Path to a PDF file.

        Returns:
            DetailedOCREvidenceResult: Structured evidence with word bounding boxes, lines, and dimensions per page.
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

        if validated_doc.extension.lower() != ".pdf":
            raise UnsupportedDocumentTypeError(
                f"PyMuPDFTextExtractor only processes '.pdf' files, but received '{validated_doc.extension}'"
            )

        inspection = self.inspector.inspect(validated_doc)

        try:
            file_bytes = validated_doc.file_path.read_bytes()
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as err:
            raise DocumentProcessingError(
                f"Corrupt or invalid PDF file '{validated_doc.file_name}': {str(err)}"
            ) from err

        try:
            pages_evidence: List[EvidencePage] = []

            for page_idx in range(inspection.total_pages):
                page = doc[page_idx]
                raw_text = page.get_text().strip()
                page_w = round(page.rect.width, 2)
                page_h = round(page.rect.height, 2)

                words_data = page.get_text("words")
                line_groups: dict = {}

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
                                confidence=None,  # PyMuPDF does not generate OCR confidence
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

                if not lines and raw_text:
                    for l_str in raw_text.splitlines():
                        if l_str.strip():
                            lines.append(
                                EvidenceLine(text=l_str.strip(), confidence=None, bounding_box=None, words=[])
                            )

                pages_evidence.append(
                    EvidencePage(
                        page_number=page_idx + 1,
                        width=page_w,
                        height=page_h,
                        raw_text=raw_text,
                        lines=lines,
                    )
                )

            return DetailedOCREvidenceResult(
                engine="pymupdf",
                file_name=validated_doc.file_name,
                total_pages=inspection.total_pages,
                pages=pages_evidence,
            )
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def extract_direct_text(document: Union[ValidatedDocument, str, Path]) -> DirectTextExtractionResult:
    """
    Convenience function to extract embedded text from a PDF document using PyMuPDF.

    Args:
        document: ValidatedDocument or path to PDF file.

    Returns:
        DirectTextExtractionResult: Structured extraction result.
    """
    extractor = PyMuPDFTextExtractor()
    return extractor.extract(document)


def extract_pymupdf_evidence(
    document: Union[ValidatedDocument, str, Path]
) -> DetailedOCREvidenceResult:
    """
    Convenience function to extract detailed page-by-page layout evidence using PyMuPDF.

    Args:
        document: ValidatedDocument or path to PDF file.

    Returns:
        DetailedOCREvidenceResult: Structured evidence with bounding boxes per page.
    """
    extractor = PyMuPDFTextExtractor()
    return extractor.extract_evidence(document)
