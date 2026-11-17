"""Semantic-stage contract, lineage, and privacy tests with a fake Gemini client."""

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

import pytest
from autopsy_sdk.testing import InMemoryCapture, assert_contract
from google.genai import types
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import autopsy_sdk as autopsy
from app.claim_document_intake.models import Claim, ClaimDocument, Document, IntakeClaim
from app.document_processing.models import ProcessedDocument, ProcessedPage, ProcessingRun
from app.information_extraction.content_service import DocumentContentService
from app.information_extraction.schemas import DocumentExtraction, ExtractedFact, FieldEvidence
from app.shared.database import Base


@pytest.mark.parametrize("fixture", ["healthy", "mismatch", "hallucinated_quote"])
def test_semantic_stages_emit_safe_contract_spans_and_lineage(tmp_path, fixture):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    claim_key, document_key, run_key = uuid4(), uuid4(), uuid4()
    checksum = hashlib.sha256(b"fixture-source").hexdigest()
    page_text = "HOSPITAL BILL patient Jordan Sample admission date 2026-11-16 invoice."

    with factory() as db:
        claim = IntakeClaim(
            id=claim_key, claim_id=f"CLM-{uuid4().hex.upper()}", policyholder_name="Jordan Sample",
            age=39, policy_number="POL-558", incident_date=date(2026, 11, 16),
            description="Synthetic telemetry fixture.", claimed_amount=Decimal("125.00"),
        )
        db.add(claim)
        db.flush()
        legacy = Claim(customer_name=claim.policyholder_name, claim_amount=claim.claimed_amount, status="RECEIVED")
        db.add(legacy)
        db.flush()
        claim.legacy_id = legacy.id
        intake = ClaimDocument(
            id=document_key, claim_id=claim.claim_id, document_slot=0, document_type="hospital_bill",
            original_file_name="bill.pdf", stored_file_name="bill.pdf", storage_path="synthetic/bill.pdf",
            mime_type="application/pdf", file_size_bytes=100, checksum_sha256=checksum,
        )
        stored = Document(claim_id=legacy.id, document_type="hospital_bill", file_name="bill.pdf",
                          file_path="synthetic/bill.pdf")
        db.add_all([intake, stored])
        db.flush()
        processing_run = ProcessingRun(
            id=run_key, claim_id=claim.claim_id, config_version="span-test", status="COMPLETED",
            started_at=now, completed_at=now,
        )
        db.add(processing_run)
        db.flush()
        processed = ProcessedDocument(
            run_id=run_key, document_id=stored.id, intake_document_id=document_key,
            claim_id=claim.claim_id, role="hospital_bill", attempt_number=1,
            checksum_sha256=checksum, status="COMPLETED", disposition="ACCEPTED",
            started_at=now, completed_at=now,
        )
        db.add(processed)
        db.flush()
        db.add(ProcessedPage(
            processed_document_id=processed.id, page_number=1, status="COMPLETED",
            quality_status="PASS", extraction_method="DIRECT_TEXT", engine="pymupdf",
            disposition="ACCEPTED", started_at=now, completed_at=now, raw_text=page_text,
        ))
        db.commit()
        processed_id = processed.id
        intake_claim_id = claim.claim_id
        stored_document_id = stored.id

    service = DocumentContentService(model="gemini-test")
    detected_type = "discharge_summary" if fixture == "mismatch" else "hospital_bill"

    class FakeResponse:
        text = json.dumps({
            "detected_type": detected_type,
            "disposition": "mismatch" if fixture == "mismatch" else "accepted",
            "evidence": [
                {"page_number": 1, "quote": "HOSPITAL BILL"},
                {"page_number": 1, "quote": "Jordan Sample"},
            ],
        })
        candidates = [type("Candidate", (), {"finish_reason": "STOP"})()]
        usage_metadata = type("Usage", (), {"prompt_token_count": 21, "candidates_token_count": 13})()
        model_version = "gemini-test-v1"

    class FakeModels:
        @staticmethod
        def generate_content(**_kwargs):
            return FakeResponse()

    fake_client = type("FakeClient", (), {"models": FakeModels()})()
    service._client = lambda: (fake_client, types)

    if fixture != "mismatch":
        fact_quote = "2026-11-16" if fixture == "healthy" else "2026-11-17"
        service.extract = lambda _pages, _detected, _subtype: (
            DocumentExtraction(subtype="hospital_bill", facts=[ExtractedFact(
                field_name="admission_date", raw_value=fact_quote, normalized_value=fact_quote,
                field_status="found", evidence=[FieldEvidence(page_number=1, quote=fact_quote)],
            )]),
            {
                "status": "review_required" if fixture == "hallucinated_quote" else "passed",
                "reasons": ["Unsupported evidence for admission_date: page 1."]
                    if fixture == "hallucinated_quote" else [],
                "processed_pages": [1], "expected_pages": [1], "page_coverage_complete": True,
                "batch_count": 1, "conflicting_fields": [], "consistency_warnings": [],
            },
        )

    with factory() as db, InMemoryCapture() as capture:
        autopsy.set_pipeline("insurance-claims", "2.0.0")
        source_id = autopsy.artifact_id("source_document", {"sha256": checksum}, item_id=str(document_key))
        with autopsy.run(
            entity_id=claim_key, run_id=run_key,
            items={str(document_key): "proof"}, trigger="test",
        ):
            with autopsy.stage(
                "document_processing", item_id=str(document_key), item_role="proof", inputs=[source_id],
            ) as document_stage:
                document_stage.record_artifact("page_text", [{
                    "page": 1, "method": "DIRECT_TEXT", "text": page_text,
                }], item_id=str(document_key))
            processing = db.get(ProcessedDocument, processed_id)
            outcome = service.process_and_persist(
                db, processing, None, declared_type="hospital_bill", checksum=checksum,
            )

    spans = capture.spans
    manifest = {"stages": [
        {"name": "document_processing", "scope": "item"},
        {"name": "content_classification", "scope": "item"},
        {"name": "information_extraction", "scope": "item"},
        {"name": "extraction_validation", "scope": "item"},
    ]}
    assert assert_contract(spans, manifest) == "A"
    stages = {span.attributes["pipeline.stage.name"]: span for span in spans
              if span.attributes.get("pipeline.span.role") == "stage"}
    assert "content_classification" in stages
    all_events = [event for span in spans for event in span.events]
    evidence_quotes = next(event for event in all_events
                           if event.attributes.get("pipeline.check.id") == "classification.evidence_quotes")
    assert evidence_quotes.attributes["pipeline.check.result"] == "pass"

    if fixture == "mismatch":
        assert outcome == "content_mismatch"
        mismatch = next(event for event in all_events
                        if event.attributes.get("pipeline.check.id") == "classification.matches_declared")
        assert mismatch.attributes["pipeline.check.result"] == "fail"
        assert "information_extraction" not in stages
    else:
        assert "information_extraction" in stages
        assert "extraction_validation" in stages
        page_coverage = next(event for event in all_events
                             if event.attributes.get("pipeline.check.id") == "extraction.page_coverage")
        assert page_coverage.attributes["pipeline.check.result"] == "pass"
        semantic_ops = [span for span in spans if span.name.startswith("generate_content ")]
        assert semantic_ops
        assert semantic_ops[0].attributes["gen_ai.operation.name"] == "generate_content"
        assert semantic_ops[0].attributes["gen_ai.provider.name"] == "gcp.gemini"
        assert semantic_ops[0].attributes["pipeline.item.index"] == 1
        serialized_attributes = repr(semantic_ops[0].attributes)
        assert "HOSPITAL BILL" not in serialized_attributes
        assert "Jordan Sample" not in serialized_attributes

        produced = set()
        external = {source_id}
        for span in spans:
            if span.attributes.get("pipeline.span.role") != "stage":
                continue
            inputs = span.attributes["pipeline.artifact.input_ids"]
            assert all(artifact in produced or artifact in external for artifact in inputs)
            produced.update(span.attributes["pipeline.artifact.output_ids"])

        if fixture == "hallucinated_quote":
            assert outcome == "review_required"
            quote_check = next(event for event in all_events
                               if event.attributes.get("pipeline.check.id") == "extraction.quote_support"
                               and event.attributes.get("pipeline.check.result") == "fail")
            assert quote_check.attributes["pipeline.check.field"] == "admission_date"
            assert quote_check.attributes["pipeline.check.target_artifact_id"] in stages["information_extraction"].attributes["pipeline.artifact.output_ids"]
        else:
            assert outcome == "accepted"
            assert stages["extraction_validation"].attributes["pipeline.artifact.output_ids"]

    private_values = ("Jordan Sample", "POL-558", "125.00", "2026-11-17")
    for span in spans:
        values = [repr(value) for value in span.attributes.values()]
        values.extend(repr(value) for event in span.events for value in event.attributes.values())
        for private_value in private_values:
            assert all(private_value not in value for value in values)
    engine.dispose()
