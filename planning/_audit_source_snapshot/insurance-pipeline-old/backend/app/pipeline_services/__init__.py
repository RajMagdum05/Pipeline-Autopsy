"""
Pipeline Services Package
=========================
Contains the decoupled backend services executing the enterprise claims pipeline:

- `ocr`: Ingestion, document inspection, PyMuPDF / Tesseract extraction, image preprocessing, quality validation.
- `extraction`: LLM-based structured information extraction using Gemini with schema validation.
- `rule_engine`: Deterministic business rule engine evaluating claim eligibility and coverage bounds.
- `orchestrator`: End-to-end pipeline execution and OpenTelemetry trace management.
"""

from app.pipeline_services.ocr import (
    OCRApplicationService,
    OCRQualityValidator,
    process_document,
    DocumentProcessingError,
    DocumentNotFoundError,
)
from app.pipeline_services.extraction import (
    ExtractionServiceError,
    ExtractionValidationError,
    extract_claim_from_validated_ocr,
    extract_claim_information,
    validate_and_finalize_extraction,
)
from app.pipeline_services.rule_engine import (
    RuleEngineError,
    evaluate_claim_rules,
)
from app.pipeline_services.orchestrator import (
    PipelineExecutionError,
    run_claim_pipeline,
)

__all__ = [
    # OCR
    "OCRApplicationService",
    "OCRQualityValidator",
    "process_document",
    "DocumentProcessingError",
    "DocumentNotFoundError",
    # Extraction
    "ExtractionServiceError",
    "ExtractionValidationError",
    "extract_claim_from_validated_ocr",
    "extract_claim_information",
    "validate_and_finalize_extraction",
    # Rule Engine
    "RuleEngineError",
    "evaluate_claim_rules",
    # Orchestrator
    "PipelineExecutionError",
    "run_claim_pipeline",
]

