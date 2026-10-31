import os
import json
import logging
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from google import genai
from google.genai import types

from app.schemas import (
    OCRResult,
    OCRPage,
    ExtractedClaimInformation,
    ClaimSourceReference,
    ClaimExtractionResult,
    ValidatedExtractionResult,
)
from app.prompts import (
    EXTRACTION_PROMPT_VERSION,
    build_gemini_extraction_prompt,
)
from app.pipeline_services.ocr.quality_validator import OCRQualityValidator, OCRDocumentValidationResult
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.telemetry.attributes import (
    PIPELINE_NAME,
    PIPELINE_NAME_VAL,
    PIPELINE_VERSION,
    PIPELINE_VERSION_VAL,
    EXECUTION_ID,
    EXECUTION_ENTITY_ID,
    STAGE_NAME,
    STAGE_VERSION,
    STAGE_STATUS,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    RETRY_COUNT,
    RETRY_REASON,
)

tracer = trace.get_tracer("enterprise_pipeline.extraction")

logger = logging.getLogger("enterprise_pipeline.extraction")

PREFERRED_GEMINI_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
]


class ExtractionServiceError(Exception):
    """Base exception class for Information Extraction service failures."""
    pass


class ExtractionConfigError(ExtractionServiceError):
    """Raised when required configuration (e.g., GEMINI_API_KEY) is missing or invalid."""
    pass


class ExtractionAPIError(ExtractionServiceError):
    """Raised when Gemini API request fails, times out, or returns empty response."""
    pass


class ExtractionValidationError(ExtractionServiceError):
    """Raised when Gemini extraction response fails structural schema validation."""
    def __init__(self, message: str, errors: Optional[List[str]] = None, failed_result: Optional[ValidatedExtractionResult] = None):
        super().__init__(message)
        self.errors = errors or [message]
        self.failed_result = failed_result


class ValidatedPageContext(BaseModel):
    """
    Context representation of a validated OCR page passed to Information Extraction.
    """
    document_id: Union[int, str] = Field(..., description="Source document database ID")
    page_number: int = Field(..., description="1-based page number")
    file_name: str = Field(default="document.pdf", description="Base filename of source document")
    document_type: str = Field(default="claim_document", description="Category/type of document")
    extraction_method: str = Field(..., description="DIRECT_TEXT or TESSERACT_OCR")
    raw_text: str = Field(..., description="Clean extracted text content")
    validation_status: str = Field(..., description="PASS or WARNING")


class ClaimOCRInputPayload(BaseModel):
    """
    Clean extraction input payload gathering all validated OCR page results for a single claim.
    """
    claim_id: Union[int, str] = Field(..., description="Target claim ID")
    total_documents: int = Field(..., description="Total documents gathered")
    total_validated_pages: int = Field(..., description="Total validated pages included")
    validated_pages: List[ValidatedPageContext] = Field(default_factory=list, description="Validated page contexts")


def build_claim_extraction_input(
    claim_id: Union[int, str],
    documents: List[Dict[str, Any] | Any],
) -> ClaimOCRInputPayload:
    """
    Gathers all validated OCR page results for a single claim_id, filtering out failed pages.

    Args:
        claim_id: Target claim database ID.
        documents: List of Document ORM models or dict representations.

    Returns:
        ClaimOCRInputPayload: Clean input payload containing validated page contexts.
    """
    validated_pages: List[ValidatedPageContext] = []
    doc_ids_set = set()

    validator = OCRQualityValidator()

    for doc in documents:
        doc_id = (doc.get("id") if isinstance(doc, dict) else getattr(doc, "id", None))
        doc_type = (doc.get("document_type") if isinstance(doc, dict) else getattr(doc, "document_type", None)) or "claim_document"
        file_name = (doc.get("file_name") if isinstance(doc, dict) else getattr(doc, "file_name", None)) or "document.pdf"
        ocr_res_raw = (doc.get("ocr_result") if isinstance(doc, dict) else getattr(doc, "ocr_result", None))

        if not doc_id or not ocr_res_raw:
            continue

        doc_ids_set.add(doc_id)

        if isinstance(ocr_res_raw, dict):
            ocr_obj = OCRResult(**ocr_res_raw)
        elif isinstance(ocr_res_raw, OCRResult):
            ocr_obj = ocr_res_raw
        else:
            continue

        doc_val = validator.validate_document(ocr_obj)

        for idx, page in enumerate(ocr_obj.pages):
            page_val = doc_val.page_validations[idx] if idx < len(doc_val.page_validations) else None
            page_status = page_val.status if page_val else getattr(page, "status", "PASS")

            # Reject FAIL pages (e.g. empty or unreadable text)
            if page_status == "FAIL":
                logger.info(f"Skipping page {page.page_number} of Document #{doc_id} due to validation status FAIL.")
                continue

            ext_method = getattr(page, "extraction_method", "DIRECT_TEXT")
            raw_text = (page.raw_text or "").strip()

            if not raw_text:
                continue

            validated_pages.append(
                ValidatedPageContext(
                    document_id=doc_id,
                    page_number=page.page_number,
                    file_name=file_name,
                    document_type=doc_type,
                    extraction_method=ext_method,
                    raw_text=raw_text,
                    validation_status=page_status,
                )
            )

    return ClaimOCRInputPayload(
        claim_id=claim_id,
        total_documents=len(doc_ids_set),
        total_validated_pages=len(validated_pages),
        validated_pages=validated_pages,
    )


def format_llm_prompt_from_payload(payload: ClaimOCRInputPayload) -> str:
    """
    Formats clean text prompt for LLM extraction from a ClaimOCRInputPayload.
    Excludes word-level bounding boxes while keeping document/page context clear.
    """
    prompt_sections: List[str] = [
        f"Target Claim ID: #{payload.claim_id}",
        "Gathered Document Contexts:",
        "========================================================================",
    ]

    for pg in payload.validated_pages:
        header = f"--- DOCUMENT #{pg.document_id} ({pg.document_type} - '{pg.file_name}') | PAGE #{pg.page_number} [Method: {pg.extraction_method}, Quality: {pg.validation_status}] ---"
        prompt_sections.append(header)
        prompt_sections.append(pg.raw_text)
        prompt_sections.append("------------------------------------------------------------------------\n")

    return "\n".join(prompt_sections)


def validate_and_finalize_extraction(
    raw_response: Union[str, Dict[str, Any]],
    claim_id: Union[int, str],
    execution_id: str,
    extraction_model: str = "gemini-3-flash-preview",
    extraction_prompt_version: str = EXTRACTION_PROMPT_VERSION,
    db_session: Any = None,
    payload: Optional[ClaimOCRInputPayload] = None,
) -> ValidatedExtractionResult:
    """
    Performs structural validation on the Gemini extraction response and builds
    a clean ValidatedExtractionResult object ready for the Rule Engine.

    If validation fails:
    - Sets extraction_status = "FAILED"
    - Sets ready_for_rule_engine = False
    - Preserves failure reasons in validation_errors
    - Persists failure record to DB
    - Raises ExtractionValidationError so it is NOT passed to Rule Engine.

    If validation succeeds:
    - Sets extraction_status = "VALIDATED"
    - Sets ready_for_rule_engine = True
    - Persists VALIDATED result to DB
    - Returns clean ValidatedExtractionResult.
    """
    validation_errors: List[str] = []
    data: Dict[str, Any] = {}

    with tracer.start_as_current_span("extraction_validation") as span:
        span.set_attribute("claim_id", claim_id)
        span.set_attribute("execution_id", execution_id)
        span.set_attribute("extraction_model", extraction_model)

        if not raw_response:
            validation_errors.append("Extraction response is null or empty.")
        elif isinstance(raw_response, str):
            cleaned_str = raw_response.strip()
            if cleaned_str.startswith("```json"):
                cleaned_str = cleaned_str[7:]
            if cleaned_str.startswith("```"):
                cleaned_str = cleaned_str[3:]
            if cleaned_str.endswith("```"):
                cleaned_str = cleaned_str[:-3]
            cleaned_str = cleaned_str.strip()

            try:
                parsed = json.loads(cleaned_str)
                if isinstance(parsed, dict):
                    data = parsed
                else:
                    validation_errors.append(f"JSON root must be an object, got {type(parsed)}")
            except Exception as json_err:
                validation_errors.append(f"Response is not valid JSON: {str(json_err)}")
        elif isinstance(raw_response, dict):
            data = raw_response
        else:
            validation_errors.append(f"Invalid raw response type: {type(raw_response)}")

        # Check additional_information dictionary layout
        if "additional_information" in data and data["additional_information"] is not None:
            if not isinstance(data["additional_information"], dict):
                validation_errors.append(f"'additional_information' must be a dict, got {type(data['additional_information'])}")

        # Check source_references list layout
        parsed_source_refs: List[ClaimSourceReference] = []
        if "source_references" in data and data["source_references"] is not None:
            if not isinstance(data["source_references"], list):
                validation_errors.append(f"'source_references' must be a list, got {type(data['source_references'])}")
            else:
                for idx, ref in enumerate(data["source_references"]):
                    if not isinstance(ref, dict):
                        validation_errors.append(f"Source reference index {idx} is not a dict.")
                        continue
                    if "field_name" not in ref or not ref["field_name"]:
                        validation_errors.append(f"Source reference index {idx} missing 'field_name'.")
                    if "document_id" not in ref or ref["document_id"] is None:
                        validation_errors.append(f"Source reference index {idx} missing 'document_id'.")
                    if "page_number" not in ref or ref["page_number"] is None:
                        validation_errors.append(f"Source reference index {idx} missing 'page_number'.")
                    try:
                        parsed_source_refs.append(ClaimSourceReference(**ref))
                    except Exception as ref_err:
                        validation_errors.append(f"Source reference index {idx} schema error: {ref_err}")

        # Check numeric amount field
        parsed_amount: Optional[Decimal] = None
        if "amount" in data and data["amount"] is not None:
            raw_amt = data["amount"]
            try:
                if isinstance(raw_amt, str):
                    cleaned_amt = raw_amt.replace("$", "").replace(",", "").strip()
                    parsed_amount = Decimal(cleaned_amt)
                else:
                    parsed_amount = Decimal(str(raw_amt))
            except Exception:
                validation_errors.append(f"Field 'amount' must be numeric, got invalid value '{raw_amt}'")

        # Check date field format
        date_val = data.get("date")
        if date_val is not None and not isinstance(date_val, str):
            validation_errors.append(f"Field 'date' must be a string, got {type(date_val)}")

        span.set_attribute("validation.errors_count", len(validation_errors))

        # If any structural validation errors exist, handle failure
        if validation_errors:
            span.set_attribute("validation.status", "FAILED")
            span.set_attribute("validation.ready_for_rule_engine", False)

            err_msg = f"Extraction structural validation failed with {len(validation_errors)} error(s): {'; '.join(validation_errors)}"
            span.set_status(Status(StatusCode.ERROR, err_msg))

            failed_result = ValidatedExtractionResult(
                claim_id=claim_id,
                execution_id=execution_id,
                extraction_status="FAILED",
                ready_for_rule_engine=False,
                patient_name=data.get("patient_name") if isinstance(data.get("patient_name"), str) else None,
                hospital=data.get("hospital") if isinstance(data.get("hospital"), str) else None,
                diagnosis=data.get("diagnosis") if isinstance(data.get("diagnosis"), str) else None,
                treatment=data.get("treatment") if isinstance(data.get("treatment"), str) else None,
                date=date_val if isinstance(date_val, str) else None,
                amount=parsed_amount,
                additional_information=data.get("additional_information") if isinstance(data.get("additional_information"), dict) else {},
                source_references=parsed_source_refs,
                extraction_model=extraction_model,
                extraction_prompt_version=extraction_prompt_version,
                validation_errors=validation_errors,
            )

            if db_session is not None:
                _save_extraction_record(
                    db=db_session,
                    claim_id=claim_id,
                    execution_id=execution_id,
                    payload=payload,
                    extraction_model=extraction_model,
                    extraction_status="FAILED",
                    extracted_data=data,
                    validation_errors=validation_errors,
                )

            val_exc = ExtractionValidationError(
                message=err_msg,
                errors=validation_errors,
                failed_result=failed_result,
            )
            span.record_exception(val_exc)
            raise val_exc

        # Success: Construct ValidatedExtractionResult
        span.set_attribute("validation.status", "VALIDATED")
        span.set_attribute("validation.ready_for_rule_engine", True)
        span.set_status(Status(StatusCode.OK))

        validated_obj = ValidatedExtractionResult(
            claim_id=claim_id,
            execution_id=execution_id,
            extraction_status="VALIDATED",
            ready_for_rule_engine=True,
            patient_name=data.get("patient_name"),
            hospital=data.get("hospital"),
            diagnosis=data.get("diagnosis"),
            treatment=data.get("treatment"),
            date=date_val,
            amount=parsed_amount,
            additional_information=data.get("additional_information") or {},
            source_references=parsed_source_refs,
            extraction_model=extraction_model,
            extraction_prompt_version=extraction_prompt_version,
            validation_errors=[],
        )

        if db_session is not None:
            _save_extraction_record(
                db=db_session,
                claim_id=claim_id,
                execution_id=execution_id,
                payload=payload,
                extraction_model=extraction_model,
                extraction_status="VALIDATED",
                extracted_data=json.loads(validated_obj.model_dump_json()),
                validation_errors=[],
            )

        return validated_obj


def validate_extraction_response(
    raw_response: Union[str, Dict[str, Any]],
    expected_claim_id: Optional[Union[int, str]] = None,
) -> ClaimExtractionResult:
    """
    Backward-compatible helper function for structural schema validation.
    """
    exec_id = f"exec_{uuid.uuid4().hex[:12]}"
    claim_id = expected_claim_id or 1
    val_res = validate_and_finalize_extraction(
        raw_response=raw_response,
        claim_id=claim_id,
        execution_id=exec_id,
    )
    return ClaimExtractionResult(
        claim_id=val_res.claim_id,
        patient_name=val_res.patient_name,
        hospital=val_res.hospital,
        diagnosis=val_res.diagnosis,
        treatment=val_res.treatment,
        date=val_res.date,
        amount=val_res.amount,
        additional_information=val_res.additional_information,
        source_references=val_res.source_references,
    )


def extract_claim_from_validated_ocr(
    claim_id: Union[int, str],
    documents: List[Dict[str, Any] | Any],
    db_session: Any = None,
    allow_fallback: bool = False,
    execution_id: Optional[str] = None,
) -> ValidatedExtractionResult:
    """
    Extracts one claim-level structured extraction result from validated OCR documents using Gemini API,
    validates the result against schema, and produces a clean ValidatedExtractionResult object.

    Workflow:
    1. Check GEMINI_API_KEY environment variable. Raise ExtractionConfigError if missing.
    2. Aggregate validated OCR pages across claim documents (`build_claim_extraction_input`).
    3. Format clean LLM prompt using `build_gemini_extraction_prompt`.
    4. Execute Gemini API call with model fallbacks (wrapped in information_extraction span).
    5. Perform structural validation & status finalization (`validate_and_finalize_extraction`).
    6. Persist extraction record to DB if `db_session` provided.
    7. Return validated `ValidatedExtractionResult`.
    """
    exec_id = execution_id or f"EXEC-{uuid.uuid4().hex[:12].upper()}"
    input_art_id = f"art_ocr_claim_{claim_id}"
    evidence_art_id = f"art_evidence_claim_{claim_id}"
    output_art_id = f"art_extracted_claim_{claim_id}"

    # 1. Check API Key
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        if allow_fallback:
            logger.warning("GEMINI_API_KEY missing. Using fallback parser (allow_fallback=True).")
            with tracer.start_as_current_span("information_extraction") as span:
                span.set_attribute("claim_id", claim_id)
                span.set_attribute(EXECUTION_ID, exec_id)
                span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
                span.set_attribute(PIPELINE_NAME, PIPELINE_NAME_VAL)
                span.set_attribute(PIPELINE_VERSION, PIPELINE_VERSION_VAL)
                span.set_attribute(STAGE_NAME, "information_extraction")
                span.set_attribute(STAGE_VERSION, "1.0.0")
                span.set_attribute(INPUT_ARTIFACT_IDS, [input_art_id, evidence_art_id])
                span.set_attribute(OUTPUT_ARTIFACT_IDS, [output_art_id])
                span.set_attribute("extraction.input_artifact_id", input_art_id)
                span.set_attribute("extraction.source_evidence_artifact_id", evidence_art_id)
                span.set_attribute(RETRY_COUNT, 0)
                payload = build_claim_extraction_input(claim_id, documents)
                fallback_res = _fallback_offline_extraction(payload)
                extracted_fields = ["patient_name", "hospital", "diagnosis", "treatment", "date", "amount"]
                extracted_values = {
                    "hospital": fallback_res.hospital,
                    "diagnosis": fallback_res.diagnosis,
                    "treatment": fallback_res.treatment,
                    "date": fallback_res.date,
                    "amount": str(fallback_res.amount) if fallback_res.amount is not None else None,
                }
                span.set_attribute("extraction.extracted_fields", extracted_fields)
                span.set_attribute("extraction.extracted_values", json.dumps(extracted_values))
                span.set_attribute(STAGE_STATUS, "completed")
                span.set_status(Status(StatusCode.OK))
                return validate_and_finalize_extraction(
                    raw_response=fallback_res.model_dump(),
                    claim_id=claim_id,
                    execution_id=exec_id,
                    extraction_model="offline_fallback",
                    db_session=db_session,
                    payload=payload,
                )
        raise ExtractionConfigError(
            "GEMINI_API_KEY environment variable is missing. "
            "Please add GEMINI_API_KEY to your .env file."
        )

    # 2. Gather Validated OCR Payload
    payload = build_claim_extraction_input(claim_id, documents)
    if payload.total_validated_pages == 0:
        raise ExtractionServiceError(f"No validated OCR text available for Claim #{claim_id}.")

    # 3. Format Prompt
    formatted_text = format_llm_prompt_from_payload(payload)
    full_prompt = build_gemini_extraction_prompt(claim_id=claim_id, formatted_document_text=formatted_text)

    # 4. Execute Gemini API Call with Model Fallback
    raw_response_text: Optional[str] = None
    used_model: Optional[str] = None
    api_errors: List[str] = []

    with tracer.start_as_current_span("information_extraction") as span:
        span.set_attribute("claim_id", claim_id)
        span.set_attribute(EXECUTION_ID, exec_id)
        span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
        span.set_attribute(PIPELINE_NAME, PIPELINE_NAME_VAL)
        span.set_attribute(PIPELINE_VERSION, PIPELINE_VERSION_VAL)
        span.set_attribute(STAGE_NAME, "information_extraction")
        span.set_attribute(STAGE_VERSION, "1.0.0")
        span.set_attribute(INPUT_ARTIFACT_IDS, [input_art_id, evidence_art_id])
        span.set_attribute(OUTPUT_ARTIFACT_IDS, [output_art_id])
        span.set_attribute("extraction.input_artifact_id", input_art_id)
        span.set_attribute("extraction.source_evidence_artifact_id", evidence_art_id)
        span.set_attribute("extraction.prompt_version", EXTRACTION_PROMPT_VERSION)
        span.set_attribute("extraction.total_documents", payload.total_documents)
        span.set_attribute("extraction.total_validated_pages", payload.total_validated_pages)
        span.set_attribute(RETRY_COUNT, 0)

        fallback_count = 0
        try:
            client = genai.Client(api_key=api_key)
            for model_idx, model_name in enumerate(PREFERRED_GEMINI_MODELS):
                if model_idx > 0:
                    fallback_count += 1
                    span.set_attribute(RETRY_COUNT, fallback_count)
                    if api_errors:
                        span.set_attribute(RETRY_REASON, api_errors[-1])
                try:
                    logger.info(f"Executing Information Extraction for Claim #{claim_id} using model '{model_name}'...")
                    response = client.models.generate_content(
                        model=model_name,
                        contents=full_prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                        ),
                    )
                    if response and response.text:
                        raw_response_text = response.text
                        used_model = model_name
                        break
                    else:
                        api_errors.append(f"Model '{model_name}' returned empty response text.")
                except Exception as err:
                    err_str = str(err)
                    clean_err = err_str.replace(api_key, "[REDACTED_API_KEY]")
                    logger.warning(f"Model '{model_name}' failed: {clean_err}")
                    api_errors.append(f"Model '{model_name}' error: {clean_err}")

            if not raw_response_text:
                if allow_fallback:
                    fallback_count += 1
                    span.set_attribute(RETRY_COUNT, fallback_count)
                    if api_errors:
                        span.set_attribute(RETRY_REASON, api_errors[-1])
                    logger.warning("All Gemini API model calls failed. Using fallback offline parser.")
                    fallback_res = _fallback_offline_extraction(payload)
                    span.set_attribute("extraction.model", "offline_fallback")
                    span.set_attribute("extraction.status", "FALLBACK")
                    extracted_fields = ["patient_name", "hospital", "diagnosis", "treatment", "date", "amount"]
                    extracted_values = {
                        "hospital": fallback_res.hospital,
                        "diagnosis": fallback_res.diagnosis,
                        "treatment": fallback_res.treatment,
                        "date": fallback_res.date,
                        "amount": str(fallback_res.amount) if fallback_res.amount is not None else None,
                    }
                    span.set_attribute("extraction.extracted_fields", extracted_fields)
                    span.set_attribute("extraction.extracted_values", json.dumps(extracted_values))
                    span.set_attribute(STAGE_STATUS, "completed")
                    span.set_status(Status(StatusCode.OK))
                    return validate_and_finalize_extraction(
                        raw_response=fallback_res.model_dump(),
                        claim_id=claim_id,
                        execution_id=exec_id,
                        extraction_model="offline_fallback",
                        db_session=db_session,
                        payload=payload,
                    )
                clean_errors = [e.replace(api_key, "[REDACTED_API_KEY]") for e in api_errors]
                api_exc = ExtractionAPIError(f"Gemini API execution failed across all models: {'; '.join(clean_errors)}")
                span.record_exception(api_exc)
                span.set_attribute(STAGE_STATUS, "failed")
                span.set_attribute("error.type", type(api_exc).__name__)
                span.set_attribute("error.message", str(api_exc))
                span.set_status(Status(StatusCode.ERROR, str(api_exc)))
                raise api_exc

            span.set_attribute("extraction.model", used_model or "gemini")
            span.set_attribute("extraction.status", "RAW_EXTRACTED")

            # Parse small scalar extracted values and extracted field names
            extracted_fields: List[str] = []
            extracted_values: Dict[str, Any] = {}
            if raw_response_text:
                try:
                    cleaned_str = raw_response_text.strip()
                    if cleaned_str.startswith("```json"):
                        cleaned_str = cleaned_str[7:]
                    if cleaned_str.startswith("```"):
                        cleaned_str = cleaned_str[3:]
                    if cleaned_str.endswith("```"):
                        cleaned_str = cleaned_str[:-3]
                    cleaned_str = cleaned_str.strip()
                    parsed_dict = json.loads(cleaned_str)
                    if isinstance(parsed_dict, dict):
                        extracted_fields = list(parsed_dict.keys())
                        for k, v in parsed_dict.items():
                            if k in ("patient_name", "customer_name", "insured_name", "claimant_name", "notes", "source_references", "additional_information"):
                                continue
                            if isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) < 100):
                                extracted_values[k] = v
                except Exception:
                    pass

            span.set_attribute("extraction.extracted_fields", extracted_fields)
            span.set_attribute("extraction.extracted_values", json.dumps(extracted_values))
            span.set_attribute(STAGE_STATUS, "completed")
            span.set_status(Status(StatusCode.OK))

        except Exception as exc:
            span.set_attribute(STAGE_STATUS, "failed")
            span.set_attribute("error.type", type(exc).__name__)
            span.set_attribute("error.message", str(exc))
            if not isinstance(exc, ExtractionServiceError):
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise

    # 5. Perform Validation and Finalization
    return validate_and_finalize_extraction(
        raw_response=raw_response_text,
        claim_id=claim_id,
        execution_id=exec_id,
        extraction_model=used_model or "gemini",
        db_session=db_session,
        payload=payload,
    )


def _save_extraction_record(
    db: Any,
    claim_id: Union[int, str],
    execution_id: str,
    payload: Optional[ClaimOCRInputPayload],
    extraction_model: str,
    extraction_status: str,
    extracted_data: Dict[str, Any],
    validation_errors: List[str],
):
    """
    Saves or updates an ExtractionResultRecord entity in database.
    """
    from app.models.extraction_result_record import ExtractionResultRecord

    source_doc_ids = list(set([pg.document_id for pg in payload.validated_pages])) if payload else []

    record = ExtractionResultRecord(
        claim_id=int(claim_id) if str(claim_id).isdigit() else claim_id,
        execution_id=execution_id,
        source_document_ids=source_doc_ids,
        extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
        extraction_model=extraction_model,
        extraction_status=extraction_status,
        extracted_data=extracted_data,
        validation_errors=validation_errors,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(f"Saved ExtractionResultRecord ID #{record.id} with status '{extraction_status}' for Claim #{claim_id}.")


def _fallback_offline_extraction(payload: ClaimOCRInputPayload) -> ClaimExtractionResult:
    """
    Deterministic offline extraction parser used for testing fallback scenarios.
    Reads validated OCR page texts to extract predefined fields, additional fields, and source references.
    """
    patient_name = None
    hospital = None
    diagnosis = None
    treatment = None
    date_val = None
    amount_val = None
    additional_info: Dict[str, Any] = {}
    sources: List[ClaimSourceReference] = []

    for pg in payload.validated_pages:
        lines = pg.raw_text.splitlines()
        for line in lines:
            line_str = line.strip()
            l_lower = line_str.lower()

            if "patient:" in l_lower and not patient_name:
                patient_name = line_str.split(":", 1)[1].strip()
                sources.append(ClaimSourceReference(field_name="patient_name", document_id=pg.document_id, page_number=pg.page_number, extracted_value=patient_name))
            elif "hospital:" in l_lower and not hospital:
                hospital = line_str.split(":", 1)[1].strip()
                sources.append(ClaimSourceReference(field_name="hospital", document_id=pg.document_id, page_number=pg.page_number, extracted_value=hospital))
            elif "diagnosis:" in l_lower and not diagnosis:
                diagnosis = line_str.split(":", 1)[1].strip()
                sources.append(ClaimSourceReference(field_name="diagnosis", document_id=pg.document_id, page_number=pg.page_number, extracted_value=diagnosis))
            elif "treatment:" in l_lower and not treatment:
                treatment = line_str.split(":", 1)[1].strip()
                sources.append(ClaimSourceReference(field_name="treatment", document_id=pg.document_id, page_number=pg.page_number, extracted_value=treatment))
            elif "date:" in l_lower and not date_val:
                date_val = line_str.split(":", 1)[1].strip()
                sources.append(ClaimSourceReference(field_name="date", document_id=pg.document_id, page_number=pg.page_number, extracted_value=date_val))
            elif ("amount:" in l_lower or "total bill:" in l_lower or "total amount:" in l_lower) and not amount_val:
                raw_amt = line_str.split(":", 1)[1].strip().replace("$", "").replace(",", "")
                try:
                    amount_val = Decimal(raw_amt)
                    sources.append(ClaimSourceReference(field_name="amount", document_id=pg.document_id, page_number=pg.page_number, extracted_value=str(amount_val)))
                except Exception:
                    pass
            elif "invoice #" in l_lower:
                inv_num = line_str.split("#", 1)[1].strip()
                additional_info["invoice_number"] = inv_num
                sources.append(ClaimSourceReference(field_name="invoice_number", document_id=pg.document_id, page_number=pg.page_number, extracted_value=inv_num))

    return ClaimExtractionResult(
        claim_id=payload.claim_id,
        patient_name=patient_name,
        hospital=hospital,
        diagnosis=diagnosis,
        treatment=treatment,
        date=date_val,
        amount=amount_val,
        additional_information=additional_info,
        source_references=sources,
    )


def extract_claim_information(raw_text: str) -> ExtractedClaimInformation:
    """Legacy helper function for direct text extraction."""
    payload = ClaimOCRInputPayload(
        claim_id=1,
        total_documents=1,
        total_validated_pages=1,
        validated_pages=[
            ValidatedPageContext(
                document_id=1,
                page_number=1,
                file_name="legacy_doc.pdf",
                document_type="claim_document",
                extraction_method="DIRECT_TEXT",
                raw_text=raw_text,
                validation_status="PASS",
            )
        ],
    )
    res = extract_claim_from_validated_ocr(claim_id=1, documents=[{"id": 1, "ocr_result": {"pages": [{"page_number": 1, "raw_text": raw_text, "status": "DIRECT_TEXT"}]}}], allow_fallback=True)
    return ExtractedClaimInformation(
        patient_name=res.patient_name,
        hospital=res.hospital,
        diagnosis=res.diagnosis,
        treatment=res.treatment,
        date=res.date,
        amount=res.amount,
        additional_information=res.additional_information,
        source_references=res.source_references,
    )
