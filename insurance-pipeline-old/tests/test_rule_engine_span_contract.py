import pytest
from decimal import Decimal

from opentelemetry.trace import StatusCode

from app.pipeline_services.rule_engine.rule_engine_service import (
    RuleEngineInputError,
    evaluate_claim_rules,
)
from app.schemas import ValidatedExtractionResult
from app.telemetry.attributes import (
    ERROR_MESSAGE,
    ERROR_TYPE,
    EXECUTION_ENTITY_ID,
    EXECUTION_ID,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    STAGE_NAME,
    STAGE_STATUS,
)


def make_extraction(*, status="VALIDATED", ready=True):
    return ValidatedExtractionResult(
        claim_id=81,
        execution_id="EXEC-RULE-001",
        extraction_status=status,
        ready_for_rule_engine=ready,
        patient_name="Sensitive Test Patient",
        hospital="Test Hospital",
        diagnosis="Test condition",
        treatment="Test treatment",
        date="2026-10-30",
        amount=Decimal("1200.00"),
    )


def test_rule_engine_span_success_contract(in_memory_telemetry):
    decision = evaluate_claim_rules(make_extraction())

    assert decision.claim_id == 81
    span = next(s for s in in_memory_telemetry.get_finished_spans() if s.name == "rule_engine")
    attrs = span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == "EXEC-RULE-001"
    assert attrs[EXECUTION_ENTITY_ID] == "81"
    assert attrs[STAGE_NAME] == "rule_engine"
    assert attrs[STAGE_STATUS] == "success"
    assert list(attrs[INPUT_ARTIFACT_IDS]) == ["art_entities_claim_81"]
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == ["art_decision_claim_81"]
    assert span.status.status_code == StatusCode.OK
    assert all("Sensitive Test Patient" not in str(value) for value in attrs.values())


def test_rule_engine_span_failure_contract(in_memory_telemetry):
    with pytest.raises(RuleEngineInputError):
        evaluate_claim_rules(make_extraction(status="FAILED", ready=False))

    span = next(s for s in in_memory_telemetry.get_finished_spans() if s.name == "rule_engine")
    attrs = span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == "EXEC-RULE-001"
    assert attrs[EXECUTION_ENTITY_ID] == "81"
    assert attrs[STAGE_NAME] == "rule_engine"
    assert attrs[STAGE_STATUS] == "failed"
    assert list(attrs[INPUT_ARTIFACT_IDS]) == ["art_entities_claim_81"]
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == []
    assert attrs[ERROR_TYPE] == "RuleEngineInputError"
    assert attrs[ERROR_MESSAGE] == "Rule engine evaluation failed."
    assert span.status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in span.events)
