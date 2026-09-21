from pathlib import Path
from typing import List, Union
from pydantic import BaseModel, Field
import pymupdf as fitz

from app.services.ocr.exceptions import (
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)
from app.services.ocr.document_loader import (
    DocumentLoader,
    ValidatedDocument,
    load_and_validate_document,
)


def is_meaningful_text(text: str) -> bool:
    """Checks if extracted text string contains meaningful non-whitespace characters."""
    cleaned = text.strip()
    return len(cleaned) > 0 and any(c.isalnum() for c in cleaned)


class PDFPageInspection(BaseModel):
    """
    Inspection details for a single page within a PDF document.
    """
    page_number: int = Field(..., description="1-based page index")
    has_text: bool = Field(..., description="True if page contains non-empty embedded selectable text")
    text_length: int = Field(..., description="Length of extracted embedded text in characters")
    status: str = Field(default="DIRECT_TEXT", description="Page extraction status: DIRECT_TEXT or OCR_REQUIRED")
    has_meaningful_text: bool = Field(default=True, description="True if page contains meaningful non-whitespace text")


class PDFInspectionResult(BaseModel):
    """
    Typed summary of PDF inspection using PyMuPDF.
    """
    file_name: str = Field(..., description="Base filename of the document")
    total_pages: int = Field(..., description="Total page count in the PDF")
    has_embedded_text: bool = Field(..., description="True if any page contains selectable text")
    is_scanned: bool = Field(..., description="True if PDF contains pages but no embedded text")
    pages: List[PDFPageInspection] = Field(default_factory=list, description="Per-page inspection details")
    
    # Step 3 Routing & Classification Attributes
    document_id: Union[int, str, None] = Field(default=None, description="Document database ID if applicable")
    file_type: str = Field(default="pdf", description="Document file format/type")
    is_text_based: bool = Field(default=True, description="True if document contains extractable native text")
    ocr_required: bool = Field(default=False, description="True if document requires OCR processing")
    processing_path: str = Field(default="text_extraction", description="Selected processing route: 'text_extraction' or 'ocr'")
    direct_text_pages_count: int = Field(default=0, description="Count of pages with direct text")
    ocr_required_pages_count: int = Field(default=0, description="Count of pages requiring OCR")
    is_mixed_pdf: bool = Field(default=False, description="True if PDF contains both direct text pages and scanned pages")
    inspection_metadata: dict = Field(default_factory=dict, description="Additional inspection metadata")


class DocumentInspectionResult(PDFInspectionResult):
    """
    Unified inspection result covering PDFs, scanned documents, and images.
    """
    pass


class PDFInspector:
    """
    Production-grade PDF Inspector service powered by PyMuPDF.

    Determines page counts, extracts text metadata per page, and identifies
    whether a PDF has embedded selectable text or appears to be a scanned document.
    """

    def inspect(
        self,
        document: Union[ValidatedDocument, str, Path],
        document_id: Union[int, str, None] = None,
    ) -> PDFInspectionResult:
        """
        Inspects a PDF document to evaluate page structure and embedded text.

        Args:
            document: ValidatedDocument instance or path string/Path to a PDF file.
            document_id: Optional database document ID.

        Returns:
            PDFInspectionResult: Inspection summary including pages, text metrics, and routing path.

        Raises:
            UnsupportedDocumentTypeError: If the document is not a .pdf file.
            DocumentProcessingError: If the PDF is corrupt, empty (0 pages), or unreadable.
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
                f"PDFInspector only processes '.pdf' files, but received '{validated_doc.extension}'"
            )

        # Read file bytes to avoid OS file locking on corrupt documents (especially on Windows)
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
            total_pages = len(doc)
            if total_pages == 0:
                raise DocumentProcessingError(
                    f"PDF document '{validated_doc.file_name}' contains 0 pages."
                )

            pages_summary: List[PDFPageInspection] = []
            total_text_length = 0
            direct_text_pages_count = 0
            ocr_required_pages_count = 0

            for page_idx in range(total_pages):
                page = doc[page_idx]
                raw_text = page.get_text().strip()
                text_len = len(raw_text)
                has_meaningful = is_meaningful_text(raw_text)
                has_text = text_len > 0
                total_text_length += text_len

                if has_meaningful:
                    page_status = "DIRECT_TEXT"
                    direct_text_pages_count += 1
                else:
                    page_status = "OCR_REQUIRED"
                    ocr_required_pages_count += 1

                pages_summary.append(
                    PDFPageInspection(
                        page_number=page_idx + 1,
                        has_text=has_text,
                        text_length=text_len,
                        status=page_status,
                        has_meaningful_text=has_meaningful,
                    )
                )

            has_embedded_text = direct_text_pages_count > 0
            is_scanned = total_pages > 0 and direct_text_pages_count == 0
            is_mixed_pdf = direct_text_pages_count > 0 and ocr_required_pages_count > 0
            processing_path = "text_extraction" if has_embedded_text else "ocr"
            ocr_required = ocr_required_pages_count > 0

            return PDFInspectionResult(
                file_name=validated_doc.file_name,
                total_pages=total_pages,
                has_embedded_text=has_embedded_text,
                is_scanned=is_scanned,
                pages=pages_summary,
                document_id=document_id,
                file_type="pdf",
                is_text_based=has_embedded_text,
                ocr_required=ocr_required,
                processing_path=processing_path,
                direct_text_pages_count=direct_text_pages_count,
                ocr_required_pages_count=ocr_required_pages_count,
                is_mixed_pdf=is_mixed_pdf,
                inspection_metadata={
                    "total_text_length": total_text_length,
                    "file_size_bytes": validated_doc.file_size_bytes,
                    "direct_text_pages_count": direct_text_pages_count,
                    "ocr_required_pages_count": ocr_required_pages_count,
                    "is_mixed_pdf": is_mixed_pdf,
                },
            )
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


class DocumentInspector:
    """
    Unified Document Inspector for routing all supported document types (PDFs, Images).
    """

    ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

    def __init__(self):
        self.pdf_inspector = PDFInspector()

    def inspect(
        self,
        document: Union[ValidatedDocument, str, Path],
        document_id: Union[int, str, None] = None,
    ) -> DocumentInspectionResult:
        """
        Inspects an uploaded document to determine its properties and processing route.

        Routing Rules:
        - Digital PDF (with selectable text) -> processing_path: 'text_extraction', ocr_required: False
        - Scanned PDF (without selectable text) -> processing_path: 'ocr', ocr_required: True
        - Image (.png, .jpg, .jpeg) -> processing_path: 'ocr', ocr_required: True
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
            pdf_result = self.pdf_inspector.inspect(validated_doc, document_id=document_id)
            return DocumentInspectionResult(**pdf_result.model_dump())

        if ext in self.ALLOWED_IMAGE_EXTENSIONS:
            return DocumentInspectionResult(
                file_name=validated_doc.file_name,
                total_pages=1,
                has_embedded_text=False,
                is_scanned=True,
                pages=[
                    PDFPageInspection(
                        page_number=1,
                        has_text=False,
                        text_length=0,
                    )
                ],
                document_id=document_id,
                file_type="image",
                is_text_based=False,
                ocr_required=True,
                processing_path="ocr",
                inspection_metadata={
                    "image_extension": ext,
                    "file_size_bytes": validated_doc.file_size_bytes,
                },
            )

        raise UnsupportedDocumentTypeError(
            f"DocumentInspector does not support file extension '{ext}'."
        )


def inspect_pdf(
    document: Union[ValidatedDocument, str, Path],
    document_id: Union[int, str, None] = None,
) -> PDFInspectionResult:
    """Convenience function to inspect a PDF document."""
    inspector = PDFInspector()
    return inspector.inspect(document, document_id=document_id)


def inspect_document(
    document: Union[ValidatedDocument, str, Path],
    document_id: Union[int, str, None] = None,
) -> DocumentInspectionResult:
    """Convenience functional entry point to inspect any document (PDF or Image)."""
    inspector = DocumentInspector()
    return inspector.inspect(document, document_id=document_id)
