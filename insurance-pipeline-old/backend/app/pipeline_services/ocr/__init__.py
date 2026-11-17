from app.pipeline_services.ocr.exceptions import (
    DocumentProcessingError,
    DocumentNotFoundError,
    NotAFileError,
    UnsupportedDocumentTypeError,
)
from app.pipeline_services.ocr.document_loader import (
    DocumentLoader,
    ValidatedDocument,
    load_and_validate_document,
)
from app.pipeline_services.ocr.pdf_inspector import (
    PDFInspector,
    PDFInspectionResult,
    PDFPageInspection,
    DocumentInspector,
    DocumentInspectionResult,
    inspect_pdf,
    inspect_document,
)
from app.pipeline_services.ocr.pymupdf_extractor import (
    PyMuPDFTextExtractor,
    DirectTextExtractionResult,
    ExtractedPageText,
    extract_direct_text,
    extract_pymupdf_evidence,
)
from app.pipeline_services.ocr.tesseract_provider import (
    TesseractOCRProvider,
    TesseractOCRResult,
    TesseractPageResult,
    StructuredWordResult,
    StructuredLineResult,
    StructuredPageResult,
    StructuredDocumentOCRResult,
    run_tesseract_ocr,
    run_tesseract_on_preprocessed_page,
)
from app.pipeline_services.ocr.evidence_extractor import (
    BoundingBox,
    EvidenceWord,
    EvidenceLine,
    EvidencePage,
    DetailedOCREvidenceResult,
    OCREvidenceExtractor,
    extract_ocr_evidence,
)
from app.pipeline_services.ocr.normalizer import (
    OCRNormalizer,
    normalize_ocr_result,
)
from app.pipeline_services.ocr.persistence_service import (
    OCRPersistenceService,
    save_ocr_result,
    get_ocr_result,
)
from app.pipeline_services.ocr.page_renderer import (
    PDFPageRenderer,
    RenderedPageImage,
    render_ocr_required_pages,
)
from app.pipeline_services.ocr.image_preprocessor import (
    DocumentImagePreprocessor,
    PreprocessedImageResult,
    preprocess_page_image,
)
from app.pipeline_services.ocr.quality_validator import (
    OCRQualityValidator,
    OCRValidationConfig,
    OCRPageValidationResult,
    OCRDocumentValidationResult,
    validate_ocr_quality,
)
from app.pipeline_services.ocr.orchestrator import (
    OCRApplicationService,
    process_document,
)

__all__ = [
    "DocumentProcessingError",
    "DocumentNotFoundError",
    "NotAFileError",
    "UnsupportedDocumentTypeError",
    "DocumentLoader",
    "ValidatedDocument",
    "load_and_validate_document",
    "PDFInspector",
    "PDFInspectionResult",
    "PDFPageInspection",
    "DocumentInspector",
    "DocumentInspectionResult",
    "inspect_pdf",
    "inspect_document",
    "PyMuPDFTextExtractor",
    "DirectTextExtractionResult",
    "ExtractedPageText",
    "extract_direct_text",
    "extract_pymupdf_evidence",
    "PDFPageRenderer",
    "RenderedPageImage",
    "render_ocr_required_pages",
    "DocumentImagePreprocessor",
    "PreprocessedImageResult",
    "preprocess_page_image",
    "TesseractOCRProvider",
    "TesseractOCRResult",
    "TesseractPageResult",
    "StructuredWordResult",
    "StructuredLineResult",
    "StructuredPageResult",
    "StructuredDocumentOCRResult",
    "run_tesseract_ocr",
    "run_tesseract_on_preprocessed_page",
    "BoundingBox",
    "EvidenceWord",
    "EvidenceLine",
    "EvidencePage",
    "DetailedOCREvidenceResult",
    "OCREvidenceExtractor",
    "extract_ocr_evidence",
    "OCRNormalizer",
    "normalize_ocr_result",
    "OCRQualityValidator",
    "OCRValidationConfig",
    "OCRPageValidationResult",
    "OCRDocumentValidationResult",
    "validate_ocr_quality",
    "OCRPersistenceService",
    "save_ocr_result",
    "get_ocr_result",
    "OCRApplicationService",
    "process_document",
]
