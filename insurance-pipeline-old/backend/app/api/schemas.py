from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


# Schema for validating incoming request JSON when creating a Claim
class ClaimCreate(BaseModel):
    customer_name: str = Field(..., min_length=1)
    claim_amount: Decimal = Field(..., gt=0)
    status: str = Field(default="processing")


# Schema for structuring the API response for Claims
class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_name: str
    claim_amount: Decimal
    status: str


class OCRWord(BaseModel):
    text: str
    confidence: float | None = None
    bounding_box: dict[str, float] | list[float] | None = None  # {"x0": ..., "y0": ..., "x1": ..., "y1": ...} or [x, y, w, h]


class OCRLine(BaseModel):
    text: str
    confidence: float | None = None
    bounding_box: dict[str, float] | list[float] | None = None  # {"x0": ..., "y0": ..., "x1": ..., "y1": ...} or [x, y, w, h]
    words: list[OCRWord] = Field(default_factory=list)


class OCRPage(BaseModel):
    document_id: int | str | None = None
    page_number: int
    width: float | None = None
    height: float | None = None
    raw_text: str
    lines: list[OCRLine] = Field(default_factory=list)
    status: str = "DIRECT_TEXT"  # "DIRECT_TEXT" or "OCR_REQUIRED" or "TESSERACT_OCR"
    extraction_method: str = "DIRECT_TEXT"  # "DIRECT_TEXT" or "TESSERACT_OCR"


class OCRResult(BaseModel):
    document_id: int | str | None = None
    status: str = "success"  # "success" or "failed"
    engine: str  # "pymupdf" or "tesseract"
    engine_version: str | None = None
    created_at: str | None = None
    processing_duration_ms: float | None = None
    processing_metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[OCRPage] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# Schema for structuring the API response for Documents
class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: int
    document_type: str
    file_name: str
    file_path: str
    ocr_status: str = "pending"
    ocr_result: OCRResult | dict[str, Any] | None = None


class ClaimSourceReference(BaseModel):
    field_name: str = Field(..., description="Target field name (e.g. patient_name, diagnosis, amount)")
    document_id: int | str = Field(..., description="Source document database ID")
    page_number: int = Field(..., description="Source 1-based page number")
    extracted_value: str | None = Field(default=None, description="Extracted field value string")


# Schema for structured information extraction from claim documents
class ExtractedClaimInformation(BaseModel):
    patient_name: str | None = None
    hospital: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    date: str | None = None
    amount: Decimal | None = None
    additional_information: dict[str, Any] = Field(default_factory=dict, description="Controlled dictionary for additional useful fields present in documents")
    source_references: list[ClaimSourceReference] = Field(default_factory=list, description="Traceable document/page source references for extracted fields")


class ClaimExtractionResult(ExtractedClaimInformation):
    claim_id: int | str = Field(..., description="Associated claim database ID")


class ValidatedExtractionResult(BaseModel):
    """
    Clean, validated Information Extraction object consumable by the Rule Engine stage.
    """
    claim_id: int | str = Field(..., description="Target claim database ID")
    execution_id: str = Field(..., description="Unique execution/request ID")
    extraction_status: str = Field(..., description="VALIDATED or FAILED")
    ready_for_rule_engine: bool = Field(..., description="True only if extraction status is VALIDATED")
    patient_name: str | None = None
    hospital: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    date: str | None = None
    amount: Decimal | None = None
    additional_information: dict[str, Any] = Field(default_factory=dict, description="Controlled additional info dict")
    source_references: list[ClaimSourceReference] = Field(default_factory=list, description="Traceable source references")
    extraction_model: str | None = None
    extraction_prompt_version: str | None = None
    validation_errors: list[str] = Field(default_factory=list, description="Validation failure reasons if FAILED")


class RuleResult(BaseModel):
    """
    Individual evaluation result for a single deterministic rule.
    """
    rule_id: str = Field(..., description="Unique deterministic rule ID (e.g. RULE_001_PATIENT_NAME_PRESENT)")
    rule_name: str = Field(..., description="Human-readable rule name")
    input_values: dict[str, Any] = Field(default_factory=dict, description="Input values evaluated")
    expected_condition: str = Field(..., description="Expected rule condition/threshold")
    actual_value: Any = Field(default=None, description="Actual value extracted")
    result: str = Field(..., description="PASS, FAIL, or MISSING_DATA")
    reason: str = Field(..., description="Detailed evaluation reason")


class RuleEngineDecision(BaseModel):
    """
    Complete claim-level deterministic Rule Engine decision output.
    """
    claim_id: int | str = Field(..., description="Target claim database ID")
    execution_id: str = Field(..., description="Unique execution/request ID")
    decision: str = Field(..., description="APPROVED, REJECTED, or FLAGGED_FOR_REVIEW")
    decision_reason: str = Field(..., description="Overall decision summary reason")
    total_rules: int = Field(..., description="Total rules evaluated")
    passed_rules: int = Field(..., description="Number of rules passed")
    failed_rules: int = Field(..., description="Number of rules failed")
    missing_data_rules: int = Field(..., description="Number of rules with missing required fields")
    evaluated_rules: list[RuleResult] = Field(default_factory=list, description="Independent evaluation results for all rules")
    created_at: str | None = Field(default=None, description="ISO timestamp")


# Schema for structured policy reasoning output
class ClaimReasoningResult(BaseModel):
    eligible: bool | None = None
    reasoning: str
    supporting_policy_text: str | None = None
    confidence: float
