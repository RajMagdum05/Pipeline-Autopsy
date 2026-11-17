"""
Legacy compatibility alias for app.pipeline_services.
All backend pipeline logic lives in `app.pipeline_services`.
"""
import sys
from app import pipeline_services

# Forward app.services.ocr to app.pipeline_services.ocr
from app.pipeline_services import (
    OCRApplicationService,
    OCRQualityValidator,
    process_document,
    DocumentProcessingError,
    DocumentNotFoundError,
    ExtractionServiceError,
    ExtractionValidationError,
    extract_claim_from_validated_ocr,
    extract_claim_information,
    validate_and_finalize_extraction,
    RuleEngineError,
    evaluate_claim_rules,
    PipelineExecutionError,
    run_claim_pipeline,
)
import app.pipeline_services.ocr as ocr
import app.pipeline_services.extraction.extraction_service as extraction_service
import app.pipeline_services.rule_engine.rule_engine_service as rule_engine_service
import app.pipeline_services.orchestrator.pipeline_orchestrator as pipeline_orchestrator

sys.modules["app.services.ocr"] = ocr
sys.modules["app.services.extraction_service"] = extraction_service
sys.modules["app.services.rule_engine_service"] = rule_engine_service
sys.modules["app.services.pipeline_orchestrator"] = pipeline_orchestrator

__all__ = [
    "OCRApplicationService",
    "OCRQualityValidator",
    "process_document",
    "DocumentProcessingError",
    "DocumentNotFoundError",
    "ExtractionServiceError",
    "ExtractionValidationError",
    "extract_claim_from_validated_ocr",
    "extract_claim_information",
    "validate_and_finalize_extraction",
    "RuleEngineError",
    "evaluate_claim_rules",
    "PipelineExecutionError",
    "run_claim_pipeline",
]
