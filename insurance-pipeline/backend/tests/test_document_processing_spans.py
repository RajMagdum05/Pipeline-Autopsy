"""Document-processing span error classification and shape checks."""

import pytest
import autopsy_sdk as autopsy
from autopsy_sdk.testing import InMemoryCapture, assert_contract

from app.document_processing.exceptions import DocumentProcessingError


def test_document_processing_error_has_safe_defaults_and_explicit_code():
    ordinary = DocumentProcessingError("Invalid stored file")
    infrastructure = DocumentProcessingError(
        "OCR runtime unavailable", error_class="infra", code="OCR_RUNTIME_UNAVAILABLE",
    )

    assert ordinary.error_class == "data"
    assert ordinary.code is None
    assert infrastructure.error_class == "infra"
    assert infrastructure.code == "OCR_RUNTIME_UNAVAILABLE"
    with pytest.raises(ValueError):
        DocumentProcessingError("bad classification", error_class="privacy")


def test_document_processing_stage_emits_contract_error_class_without_message_data():
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="01900000-0000-7000-8000-000000000001", items={
            "01900000-0000-7000-8000-000000000002": "policy",
        }):
            try:
                with autopsy.stage(
                    "document_processing", item_id="01900000-0000-7000-8000-000000000002",
                    item_role="policy", inputs=["art_source"], attempt=1,
                ):
                    raise DocumentProcessingError(
                        "Private OCR details must not be exported", error_class="infra",
                        code="OCR_RUNTIME_UNAVAILABLE",
                    )
            except DocumentProcessingError:
                pass

    spans = capture.spans
    stage = next(span for span in spans if span.attributes.get("pipeline.span.role") == "stage")
    assert stage.attributes["pipeline.error.class"] == "infra"
    assert stage.attributes["pipeline.stage.status"] == "failed"
    assert "Private OCR details" not in repr(stage.attributes)
    assert assert_contract(spans, {"stages": [{"name": "document_processing", "scope": "item"}]}) == "A"
