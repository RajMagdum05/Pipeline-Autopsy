from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Union
from pathlib import Path
import pymupdf as fitz
import pytesseract

from app.schemas import OCRResult, OCRPage, OCRLine, OCRWord
from app.services.ocr.exceptions import DocumentProcessingError
from app.services.ocr.document_loader import ValidatedDocument, load_and_validate_document
from app.services.ocr.evidence_extractor import (
    DetailedOCREvidenceResult,
    EvidencePage,
    EvidenceLine,
    EvidenceWord,
    OCREvidenceExtractor,
)


class OCRNormalizer:
    """
    Production-grade Unified OCR Normalization Layer.

    Converts engine-specific outputs (PyMuPDF, Tesseract, DetailedOCREvidenceResult)
    into a single canonical, engine-agnostic `OCRResult` schema that is 100% JSON serializable.
    """

    def normalize_evidence(
        self,
        evidence_result: DetailedOCREvidenceResult,
        document_id: Union[int, str, None] = None,
        duration_ms: Union[float, None] = None,
        extra_metadata: Union[Dict[str, Any], None] = None,
    ) -> OCRResult:
        """
        Normalizes a DetailedOCREvidenceResult into the canonical OCRResult model.

        Args:
            evidence_result: Output from OCREvidenceExtractor.
            document_id: Optional database document identifier.
            duration_ms: Processing duration in milliseconds.
            extra_metadata: Optional additional metadata dict.

        Returns:
            OCRResult: Canonical engine-agnostic OCR result.
        """
        engine_name = evidence_result.engine.lower()
        if engine_name == "pymupdf":
            engine_ver = str(fitz.__version__)
            is_scanned = False
        else:
            engine_name = "tesseract"
            try:
                engine_ver = str(pytesseract.get_tesseract_version())
            except Exception:
                engine_ver = "unknown"
            is_scanned = True

        ocr_pages: List[OCRPage] = []

        for p in evidence_result.pages:
            lines: List[OCRLine] = []

            for l in p.lines:
                words: List[OCRWord] = []
                for w in l.words:
                    word_bbox = w.bounding_box.model_dump() if w.bounding_box else None
                    words.append(
                        OCRWord(
                            text=w.text,
                            confidence=w.confidence,  # Float for Tesseract, None for PyMuPDF
                            bounding_box=word_bbox,
                        )
                    )

                line_bbox = l.bounding_box.model_dump() if l.bounding_box else None
                lines.append(
                    OCRLine(
                        text=l.text,
                        confidence=l.confidence,
                        bounding_box=line_bbox,
                        words=words,
                    )
                )

            page_status = getattr(p, "status", "DIRECT_TEXT")
            if page_status in ("TESSERACT_OCR", "OCR_REQUIRED") and (lines or p.raw_text):
                ext_method = "TESSERACT_OCR"
            elif page_status == "DIRECT_TEXT":
                ext_method = "DIRECT_TEXT"
            else:
                ext_method = "DIRECT_TEXT" if p.raw_text else "TESSERACT_OCR"

            ocr_pages.append(
                OCRPage(
                    document_id=document_id,
                    page_number=p.page_number,
                    width=p.width,
                    height=p.height,
                    raw_text=p.raw_text,
                    lines=lines,
                    status=page_status,
                    extraction_method=ext_method,
                )
            )

        direct_text_pages_count = sum(1 for page in ocr_pages if page.extraction_method == "DIRECT_TEXT")
        tesseract_ocr_pages_count = sum(1 for page in ocr_pages if page.extraction_method == "TESSERACT_OCR")
        is_mixed_pdf = direct_text_pages_count > 0 and tesseract_ocr_pages_count > 0

        if is_mixed_pdf:
            final_engine = "hybrid"
        elif tesseract_ocr_pages_count > 0:
            final_engine = "tesseract"
        else:
            final_engine = "pymupdf"

        try:
            engine_ver = str(pytesseract.get_tesseract_version()) if final_engine in ("tesseract", "hybrid") else str(fitz.__version__)
        except Exception:
            engine_ver = str(fitz.__version__)

        # Generate initial OCRResult object
        initial_ocr = OCRResult(
            document_id=document_id,
            status="success",
            engine=final_engine,
            engine_version=engine_ver,
            created_at=datetime.now(timezone.utc).isoformat(),
            processing_duration_ms=duration_ms,
            processing_metadata={},
            pages=ocr_pages,
            errors=[],
        )

        # Run Quality Validator
        from app.services.ocr.quality_validator import OCRQualityValidator
        validator = OCRQualityValidator()
        doc_validation = validator.validate_document(initial_ocr)

        metadata: Dict[str, Any] = {
            "filename": evidence_result.file_name,
            "total_pages": evidence_result.total_pages,
            "is_scanned": tesseract_ocr_pages_count > 0 and direct_text_pages_count == 0,
            "direct_text_pages_count": direct_text_pages_count,
            "tesseract_ocr_pages_count": tesseract_ocr_pages_count,
            "ocr_required_pages_count": tesseract_ocr_pages_count,
            "is_mixed_pdf": is_mixed_pdf,
            "validation": doc_validation.model_dump(),
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        initial_ocr.processing_metadata = metadata
        return initial_ocr

    def process_and_normalize(
        self,
        document: Union[ValidatedDocument, str, Path],
        document_id: Union[int, str, None] = None,
    ) -> OCRResult:
        """
        Executes end-to-end evidence extraction and normalizes output into a canonical OCRResult.

        Args:
            document: ValidatedDocument instance or path to document.
            document_id: Optional document ID.

        Returns:
            OCRResult: Fully normalized canonical OCR output.
        """
        start_time = time.time()
        extractor = OCREvidenceExtractor()
        evidence_res = extractor.extract_evidence(document)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        return self.normalize_evidence(
            evidence_result=evidence_res,
            document_id=document_id,
            duration_ms=duration_ms,
        )


def normalize_ocr_result(
    document: Union[ValidatedDocument, str, Path],
    document_id: Union[int, str, None] = None,
) -> OCRResult:
    """
    Convenience function to extract evidence and normalize it into a canonical OCRResult.

    Args:
        document: ValidatedDocument or path to document.
        document_id: Optional document database ID.

    Returns:
        OCRResult: Canonical engine-agnostic OCR result.
    """
    normalizer = OCRNormalizer()
    return normalizer.process_and_normalize(document, document_id=document_id)
