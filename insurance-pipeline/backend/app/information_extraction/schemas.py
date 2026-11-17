"""Strict, document-scoped schemas for semantic validation and extraction."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceQuote(StrictModel):
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=500)


class DocumentComponent(StrictModel):
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    detected_type: Literal[
        "policy_document", "hospital_bill", "fir_accident_report", "medical_report",
        "discharge_summary", "repair_estimate", "other_supporting_document", "unknown", "unsupported",
    ]
    subtype: str | None = None
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=10)


class Classification(StrictModel):
    detected_type: Literal[
        "policy_document", "hospital_bill", "fir_accident_report", "medical_report",
        "discharge_summary", "repair_estimate", "other_supporting_document",
        "unknown", "unsupported", "mixed_document", "unreadable",
    ]
    subtype: str | None = None
    disposition: Literal["accepted", "mismatch", "review_required", "unsupported", "unreadable"]
    reasons: list[str] = Field(default_factory=list, max_length=12)
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=20)
    components: list[DocumentComponent] = Field(default_factory=list, max_length=20)
    ambiguity: list[str] = Field(default_factory=list, max_length=12)
    policy_set_complete: Literal["yes", "no", "unknown"] = "unknown"


class FieldEvidence(StrictModel):
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=500)


class ExtractedFact(StrictModel):
    field_name: str = Field(min_length=1, max_length=100)
    raw_value: str | None = None
    normalized_value: str | None = None
    field_status: Literal["found", "missing", "unreadable", "conflicting", "not_applicable"]
    evidence: list[FieldEvidence] = Field(default_factory=list, max_length=20)
    warning: str | None = None


class DocumentExtraction(StrictModel):
    subtype: str
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class ValidationIssue(StrictModel):
    code: str = Field(min_length=1, max_length=80)
    severity: Literal["blocking", "review", "warning"]
    field_path: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=240)


class ValidationCheck(StrictModel):
    check_id: str = Field(min_length=1, max_length=80)
    outcome: Literal["pass", "fail", "not_evaluated"]
    required: bool = True
    issue_codes: list[str] = Field(default_factory=list, max_length=30)


class ExtractionValidationReport(StrictModel):
    claim_id: str | None = None
    document_id: str | None = None
    accepted_document_type: str | None = None
    extraction_attempt: int = Field(default=0, ge=0)
    input_version: str | None = None
    validator_version: str = Field(min_length=1)
    configuration_version: str = Field(min_length=1)
    overall_disposition: Literal["accepted", "review_required", "extraction_failed"]
    # Kept for existing status consumers while they transition to disposition.
    status: Literal["passed", "review_required", "failed"]
    checks: list[ValidationCheck] = Field(default_factory=list, max_length=30)
    issues: list[ValidationIssue] = Field(default_factory=list, max_length=200)
    started_at: datetime
    completed_at: datetime


class PolicyExtraction(DocumentExtraction):
    document_type: Literal["policy_document"] = "policy_document"


class PolicyScheduleExtraction(PolicyExtraction):
    policy_subtype: Literal["schedule_or_certificate"] = "schedule_or_certificate"


class PolicyWordingExtraction(PolicyExtraction):
    policy_subtype: Literal["policy_wording"] = "policy_wording"


class EndorsementExtraction(PolicyExtraction):
    policy_subtype: Literal["endorsement_or_addon"] = "endorsement_or_addon"


class CustomerInformationSheetExtraction(PolicyExtraction):
    policy_subtype: Literal["customer_information_sheet"] = "customer_information_sheet"


class HospitalBillExtraction(DocumentExtraction):
    document_type: Literal["hospital_bill"] = "hospital_bill"


class FIRAccidentReportExtraction(DocumentExtraction):
    document_type: Literal["fir_accident_report"] = "fir_accident_report"


class MedicalReportExtraction(DocumentExtraction):
    document_type: Literal["medical_report"] = "medical_report"


class DischargeSummaryExtraction(DocumentExtraction):
    document_type: Literal["discharge_summary"] = "discharge_summary"


class RepairEstimateExtraction(DocumentExtraction):
    document_type: Literal["repair_estimate"] = "repair_estimate"


class OtherSupportingDocumentExtraction(DocumentExtraction):
    document_type: Literal["other_supporting_document"] = "other_supporting_document"


EXTRACTION_SCHEMAS = {
    "policy_document": PolicyExtraction,
    "hospital_bill": HospitalBillExtraction,
    "fir_accident_report": FIRAccidentReportExtraction,
    "medical_report": MedicalReportExtraction,
    "discharge_summary": DischargeSummaryExtraction,
    "repair_estimate": RepairEstimateExtraction,
    "other_supporting_document": OtherSupportingDocumentExtraction,
}

POLICY_SUBTYPE_SCHEMAS = {
    "schedule": PolicyScheduleExtraction,
    "certificate": PolicyScheduleExtraction,
    "wording": PolicyWordingExtraction,
    "endorsement": EndorsementExtraction,
    "addon": EndorsementExtraction,
    "rider": EndorsementExtraction,
    "customer information sheet": CustomerInformationSheetExtraction,
}

ALLOWED_FIELDS = {
    "policy_document": set("insurer product_name plan_variant policy_number product_identifier uin wording_version issue_date policyholder_name insured_member_name member_identifier date_of_birth age relationship coverage_basis coverage_start coverage_end first_inception renewal_continuity endorsement_effective_date sum_insured currency sum_insured_basis bonus additional_cover restoration_terms hospitalization_benefit daycare_benefit pre_hospitalization post_hospitalization ambulance_benefit other_benefit eligibility_condition definition initial_waiting_period pre_existing_waiting_period specified_waiting_period exclusion exclusion_exception copayment deductible room_limit icu_limit sublimit geographic_restriction network_restriction endorsement rider addon waiver member_restriction claim_notification_condition claim_submission_condition required_evidence contractual_cross_reference".split()),
    "hospital_bill": set("document_title issuer hospital_name hospital_address hospital_identifier patient_name patient_identifier encounter_reference admission_reference invoice_number invoice_date admission_date discharge_date item_description service_date quantity rate amount item_amount line_item_amount category subtotal taxes discount credits total deposits balance payment_status referenced_receipt currency".split()),
    "fir_accident_report": set("document_title subtype police_station reporting_authority fir_number report_number report_date incident_date incident_time incident_location named_person person_role incident_description reported_incident_description reported_injury statement_attributed_to injury vehicle_identifier property_identifier legal_section reporter officer_name officer_identifier".split()),
    "medical_report": set("document_title subtype facility clinician laboratory patient_name patient_identifier report_date specimen_date consultation_date clinical_history diagnosis diagnosis_code test_name value unit reference_range flag finding impression medicine dosage treatment recommendation procedure".split()),
    "discharge_summary": set("document_title patient_name patient_identifier hospital_name hospital_identifier admission_date admission_time discharge_date discharge_time admission_reason diagnosis diagnosis_code relevant_history procedure treatment treatment_date clinician discharge_condition medicine dosage follow_up_instruction".split()),
    "repair_estimate": set("document_title vendor_name vendor_address estimate_number estimate_date customer_name asset_identifier vehicle_identifier reported_damage part_description labor_description quantity rate tax discount estimated_total currency terms validity".split()),
    "other_supporting_document": set("document_title subtype issuer reference_number document_date person_name person_identifier event_date service_date currency amount bill_reference receipt_number payment_status item_description quantity rate source_fact".split()),
}

REPEATABLE_FIELDS = set("insured_member_name member_identifier diagnosis named_person person_role injury vehicle_identifier property_identifier item_description service_date quantity rate amount item_amount line_item_amount taxes medicine dosage test_name value finding impression procedure part_description labor_description source_fact".split())
