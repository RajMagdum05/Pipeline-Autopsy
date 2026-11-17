import pytest

from autopsy.core.model import Observation
from autopsy.explain.bundle import build_bundle
from autopsy.explain.template import build_template


def _case(name):
    if name == "toy_short_body":
        artifact_id = "art_70af20f0e6adc941"
        result = {
            "verdict": "ROOT_CAUSE_IDENTIFIED", "trace_grade": "A",
            "findings": [{"stage": "fetch", "role": "origin",
                          "classification": "OUTPUT_CONTRACT_VIOLATION", "confidence": "supported",
                          "severity": "fail", "evidence": ["obs_001"]}],
            "observations": [Observation(
                "contract", "schema.minLength", "fail", "fetch", "body is shorter than the declared minimum",
                span_id="s1", artifact_id=artifact_id, field="body", id="obs_001",
            )],
        }
        artifacts = {artifact_id: {"kind": "page", "redacted": False,
                                   "content": {"body": "too short"}}}
    elif name == "ins_ocr_misread_bill_date":
        artifact_id = "art_page_bill"
        result = {
            "verdict": "ROOT_CAUSE_IDENTIFIED", "trace_grade": "A",
            "findings": [{"stage": "document_processing@bill", "role": "origin",
                          "classification": "OUTPUT_CONTRACT_VIOLATION", "confidence": "supported",
                          "severity": "warn", "evidence": ["obs_001"]}],
            "observations": [Observation(
                "check", "ocr.quality", "warn", "document_processing@bill",
                "low confidence; contact alice@example.com; identifier 123456789012",
                span_id="s1", artifact_id=artifact_id, id="obs_001",
            )],
        }
        artifacts = {artifact_id: {"kind": "page_text", "redacted": True,
                                   "content": "Admission Date: 2025-03-02. low_conf_ratio=0.62; "
                                              "contact alice@example.com; identifier 123456789012"}}
    else:
        result = {
            "verdict": "ROOT_CAUSE_IDENTIFIED", "trace_grade": "A",
            "findings": [{"stage": "document_processing@pol", "role": "origin",
                          "classification": "SERVICE_EXECUTION_FAILURE", "confidence": "supported",
                          "severity": "fail", "evidence": ["obs_001"]}],
            "observations": [Observation(
                "execution", "stage_failed", "fail", "document_processing@pol",
                "OCRRuntimeUnavailable: tesseract runtime unavailable", span_id="s1",
                error_class="infra", id="obs_001",
            )],
        }
        artifacts = {}
    return result, artifacts


@pytest.mark.parametrize("case", [
    "toy_short_body", "ins_ocr_misread_bill_date", "ins_policy_ocr_unreadable",
])
def test_template_explanation_snapshots(case):
    result, artifacts = _case(case)
    bundle = build_bundle(result, artifacts, evidence_level="E2")
    explanation = build_template(bundle)
    expected = {
        "source": "template",
        "summary": {
            "toy_short_body": "Origin: fetch — output contract violation (supported confidence). Evidence: schema.minLength.",
            "ins_ocr_misread_bill_date": "Origin: document_processing@bill — output contract violation (supported confidence). Evidence: ocr.quality.",
            "ins_policy_ocr_unreadable": "Origin: document_processing@pol — service execution failure (supported confidence). Evidence: stage_failed.",
        }[case],
        "narrative": {
            "toy_short_body": [
                "fetch: origin — output contract violation (supported confidence). Checks: schema.minLength",
            ],
            "ins_ocr_misread_bill_date": [
                "document_processing@bill: origin — output contract violation (supported confidence). "
                "Checks: ocr.quality. Evidence excerpt: Admission Date: 2025-03-02. low_conf_ratio=0.62; "
                "contact [REDACTED]; identifier [REDACTED]",
            ],
            "ins_policy_ocr_unreadable": [
                "document_processing@pol: origin — service execution failure (supported confidence). "
                "Checks: stage_failed",
            ],
        }[case],
        "remediation": [],
    }
    assert explanation == expected
    assert all(len(excerpt["text"]) <= 300 for excerpt in bundle["excerpts"])
    assert len(bundle["excerpts"]) <= 12
    serialized = repr(explanation)
    assert "alice@example.com" not in serialized
    assert "123456789012" not in serialized


def test_bundle_never_includes_non_e2_or_unredacted_artifacts():
    result, artifacts = _case("ins_ocr_misread_bill_date")
    assert build_bundle(result, artifacts, evidence_level="E1")["excerpts"] == []
    artifacts["art_page_bill"]["redacted"] = False
    assert build_bundle(result, artifacts, evidence_level="E2")["excerpts"] == []
