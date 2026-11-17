"""Opt-in fault hooks stay deterministic and request-scoped."""

from types import SimpleNamespace

import pytest
from autopsy_sdk.testing import InMemoryCapture

import autopsy_sdk as autopsy
from app import faults
from app.fake_gemini import FakeGemini
from app.document_processing.exceptions import DocumentProcessingError
from app.adjudication.schemas import Decision
from app.information_extraction.schemas import Classification, ExtractedFact, FieldEvidence


def test_faults_are_inert_without_explicit_enable(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "false")
    with faults.activate("ocr_misread_bill_date") as selected:
        assert selected is None
        page = SimpleNamespace(raw_text="Admission 2025-03-02")
        metrics = {"page_validations": []}
        faults.after_text_extraction({"role": "hospital_bill"}, [page], metrics)
        assert page.raw_text == "Admission 2025-03-02"
        assert metrics == {"page_validations": []}


def test_classification_and_provider_hooks_are_scoped_and_safe(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    with faults.activate("classification_mismatch"):
        mismatch = faults.before_llm("content_classification", {
            "role": "hospital_bill",
            "pages": [{"page_number": 1, "text": "HOSPITAL BILL Invoice Number 123"}],
        }, Classification)
        assert mismatch.detected_type == "discharge_summary"
        assert mismatch.disposition == "accepted"
        with pytest.raises(DocumentProcessingError) as raised:
            with faults.activate("gemini_unavailable"):
                faults.before_llm("content_classification", {"role": "hospital_bill"}, Classification)
        assert raised.value.error_class == "infra"
        assert raised.value.code == "GENAI_REQUEST_FAILED"


def test_extraction_faults_distinguish_caught_and_uncaught_grounding(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    fact = ExtractedFact(
        field_name="admission_date", raw_value="2025-03-02", normalized_value="2025-03-02",
        field_status="found", evidence=[FieldEvidence(page_number=1, quote="Admission 2025-03-02")],
    )
    with faults.activate("extraction_hallucinate_caught"):
        faults.after_extraction({"role": "hospital_bill"}, [fact])
        assert fact.raw_value == "2024-03-02"
        assert faults.validator_overrides({"role": "hospital_bill"}) == {}
    with faults.activate("extraction_wrong_date_uncaught"):
        assert faults.validator_overrides({"role": "hospital_bill"}) == {
            "skip_quote_fields": {"admission_date"},
        }


def test_ocr_faults_change_only_the_named_document_quality(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    page = SimpleNamespace(raw_text="Admission Date: 2025-03-02")
    metrics = {"page_validations": [{"page_number": 1, "reasons": []}]}
    with faults.activate("ocr_misread_bill_date"):
        faults.after_text_extraction({"role": "hospital_bill"}, [page], metrics)
    assert page.raw_text == "Admission Date: 2024-03-02"
    assert metrics["low_confidence_word_proportion"] == 0.62
    assert metrics["page_validations"][0]["status"] == "WARNING"

    page = SimpleNamespace(raw_text="Policy coverage dates")
    metrics = {"page_validations": [{"page_number": 1, "reasons": []}]}
    with faults.activate("policy_ocr_unreadable"):
        faults.after_text_extraction({"role": "policy_document"}, [page], metrics)
    assert page.raw_text == ""
    assert metrics["overall_status"] == "FAIL"
    assert metrics["page_validations"][0]["disposition"] == "RETRY_REQUIRED"


def test_fake_gemini_uses_recorded_synthetic_responses():
    fake = FakeGemini()
    prompt = "DEMO HEALTH INSURANCE POLICY SCHEDULE Policyholder: Alex Demo"
    response = fake.models.generate_content(contents=prompt)
    assert Classification.model_validate_json(response.text).detected_type == "policy_document"
    assert response.model_version == "recorded-synthetic"


def test_fake_gemini_runs_service_without_live_credentials(monkeypatch):
    import json
    from pathlib import Path

    from app.information_extraction.content_service import DocumentContentService

    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    monkeypatch.setenv("AUTOPSY_FAKE_GEMINI", "true")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    results = json.loads((Path(__file__).resolve().parents[2] / "demo_documents" /
                          "gemini_demo_results.json").read_text(encoding="utf-8"))
    document = results["documents"][0]
    pages = document["page_text_sent_to_model"]
    service = DocumentContentService(model="recorded-synthetic")
    classification, _ = service.classify(pages, "policy_document")
    extracted, validation = service.extract(pages, classification.detected_type, classification.subtype)
    assert classification.disposition == "accepted"
    assert validation["status"] == "passed"
    assert any(fact.field_name == "policy_number" and fact.raw_value == "DEMO-POL-2048"
               for fact in extracted.facts)


def test_run_fault_label_is_written_only_to_the_execution_span():
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="fault-run") as execution:
            execution.set_attribute("pipeline.fault.name", "ocr_misread_bill_date")
            with autopsy.stage("document_processing", item_id="synthetic-doc"):
                pass
    run_span = next(span for span in capture.spans
                    if span.attributes.get("pipeline.span.role") == "execution")
    stage_span = next(span for span in capture.spans
                      if span.attributes.get("pipeline.span.role") == "stage")
    assert run_span.attributes["pipeline.fault.name"] == "ocr_misread_bill_date"
    assert "pipeline.fault.name" not in stage_span.attributes


def test_final_result_fault_flips_only_when_selected(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    decision = Decision(decision="APPROVED", rules_version="test-v1", rules=())
    with faults.activate("clean_rejection"):
        assert faults.after_adjudication(decision).decision == "APPROVED"
    with faults.activate("final_mismatch"):
        assert faults.after_adjudication(decision).decision == "REJECTED"
