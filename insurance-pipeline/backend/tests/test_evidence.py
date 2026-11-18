"""Privacy controls for insurance evidence uploads."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autopsy_sdk import run, stage
from autopsy_sdk.api import _set_artifact_uploader
from autopsy_sdk.upload import EvidenceUploader

from app.observability.evidence import (
    evidence_kinds, evidence_level, extracted_values, page_text_excerpt,
    page_text_source, redact_document_facts,
)


class CaptureHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.requests.append(json.loads(self.rfile.read(length)))
        self.send_response(201)
        self.end_headers()

    def log_message(self, *_args):
        pass


def test_evidence_controls_default_to_e1_and_intersect_manifest(monkeypatch):
    monkeypatch.delenv("AUTOPSY_EVIDENCE_LEVEL", raising=False)
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "page_text,document_facts,claim_form,claim_result")
    assert evidence_level() == "E1"
    assert evidence_kinds() == {"page_text", "document_facts", "claim_result"}


def test_claim_result_is_allowed_only_when_requested(monkeypatch):
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "claim_result,decision,other")
    assert evidence_kinds() == {"claim_result", "decision"}


def test_page_excerpt_selects_value_lines_and_masks_identifiers():
    pages = [
        {"page": 1, "method": "DIRECT_TEXT", "text": "Unrelated page header"},
        {"page": 2, "method": "OCR", "text": "Total INR 125.00 email alice@example.com phone +1 (415) 555-1234"},
        {"page": 3, "method": "OCR", "text": "Unrelated footer"},
    ]
    text = page_text_source(pages)
    result = page_text_excerpt(pages, ["125.00"])
    assert "Total INR 125.00" in result
    assert "Unrelated page header" not in result
    assert "Unrelated footer" not in result
    assert "alice@example.com" not in result
    assert "555-1234" not in result
    assert "125.00" in text


def test_document_facts_mask_nonapproved_fields_and_preserve_explicit_grounding_fields():
    facts = {"facts": [
        {"field_name": "patient_name", "field_status": "found",
         "raw_value": "Jordan Sample", "normalized_value": "Jordan Sample",
         "evidence": [{"page_number": 1, "quote": "Patient Jordan Sample"}]},
        {"field_name": "admission_date", "field_status": "found",
         "raw_value": "2026-11-16", "normalized_value": "2026-11-16",
         "evidence": [{"page_number": 1, "quote": "Admission 2026-11-16"}]},
    ]}
    values = extracted_values(facts)
    redacted = redact_document_facts(facts, keep_fields={"admission_date"})
    assert values == ["Jordan Sample", "2026-11-16"]
    assert redacted["facts"][0]["raw_value"] == "[REDACTED]"
    assert redacted["facts"][0]["evidence"][0]["quote"] == "[REDACTED]"
    assert redacted["facts"][1]["raw_value"] == "2026-11-16"
    assert facts["facts"][0]["raw_value"] == "Jordan Sample"


def test_e2_fake_server_uploads_only_allowed_redacted_artifacts(monkeypatch):
    monkeypatch.setenv("AUTOPSY_EVIDENCE_LEVEL", "E2")
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "page_text,document_facts,claim_form")
    CaptureHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    uploader = EvidenceUploader(f"http://127.0.0.1:{server.server_port}", evidence_kinds=evidence_kinds())
    _set_artifact_uploader(uploader)
    pages = [{"page": 1, "method": "OCR", "text":
              "Total INR 125.00 alice@example.com +1 (415) 555-1234\nUnrelated footer"}]
    facts = {"facts": [{"field_name": "total", "field_status": "found",
                         "raw_value": "125.00", "normalized_value": "125.00",
                         "evidence": [{"page_number": 1, "quote": "Total INR 125.00"}]}]}
    try:
        with run(run_id="evidence-run"):
            with stage("information_extraction") as current:
                page_id = current.record_artifact("page_text", pages)
                uploaded_page_id = current.upload_evidence(
                    "page_text", pages, excerpt_values=extracted_values(facts),
                    upload_content=page_text_source(pages),
                    stage_name="document_processing",
                )
                current.record_artifact(
                    "document_facts", facts,
                    upload_content=redact_document_facts(facts, keep_fields={"total"}),
                    upload_redaction="fields",
                )
                current.record_artifact("claim_form", {"secret": "never uploaded"})
        assert uploaded_page_id == page_id
        assert uploader.flush(3)
    finally:
        _set_artifact_uploader(None)
        uploader.shutdown()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    payloads = CaptureHandler.requests
    assert len(payloads) == 2
    page = next(payload for payload in payloads if payload["kind"] == "page_text")
    extracted = next(payload for payload in payloads if payload["kind"] == "document_facts")
    assert "Total INR 125.00" in page["content"]
    assert "Unrelated footer" not in page["content"]
    assert "alice@example.com" not in page["content"]
    assert "555-1234" not in page["content"]
    assert page["redacted"] is True and page["redaction"] == "excerpt"
    assert page["stage"] == "document_processing"
    assert extracted["content"]["facts"][0]["raw_value"] == "125.00"
    assert extracted["redacted"] is True and extracted["redaction"] == "fields"
    assert all(payload["kind"] != "claim_form" for payload in payloads)


def test_e2_decision_and_claim_result_upload_only_minimized_fields(monkeypatch):
    from app.adjudication.schemas import Decision, InputReference, RuleResult
    from app.final_result.service import build_final_result
    from app.orchestrator.service import _record_decision_and_final_result

    monkeypatch.setenv("AUTOPSY_EVIDENCE_LEVEL", "E2")
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "decision,claim_result")
    CaptureHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    uploader = EvidenceUploader(f"http://127.0.0.1:{server.server_port}", evidence_kinds=evidence_kinds())
    _set_artifact_uploader(uploader)
    decision = Decision(
        decision="REJECTED", rules_version="adjudication-rules-v1",
        rules=(RuleResult(
            rule_id="rule.service_in_coverage", result="fail", consequence="REJECT",
            reason_code="SERVICE_BEFORE_COVERAGE",
            inputs=(InputReference(document_id="private-document-id", field="admission_date"),),
        ),),
    )
    claim_result = build_final_result(decision, claim_id="private-claim-id", run_id="private-run-id")
    try:
        with run(run_id="evidence-run"):
            _record_decision_and_final_result(decision, claim_result)
        assert uploader.flush(3)
    finally:
        _set_artifact_uploader(None)
        uploader.shutdown()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    payloads = {payload["kind"]: payload for payload in CaptureHandler.requests}
    assert set(payloads) == {"decision", "claim_result"}
    assert payloads["decision"]["content"] == {
        "decision": "REJECTED",
        "rules_version": "adjudication-rules-v1",
        "rules": [{
            "rule_id": "rule.service_in_coverage", "result": "fail",
            "consequence": "REJECT", "reason_code": "SERVICE_BEFORE_COVERAGE",
        }],
    }
    assert payloads["claim_result"]["content"] == {
        "decision": "REJECTED", "payable_amount": None, "message_code": "CLAIM_REJECTED",
    }
    for payload in payloads.values():
        assert payload["redacted"] is True and payload["redaction"] == "fields"
        assert "private-claim-id" not in json.dumps(payload["content"])
        assert "private-document-id" not in json.dumps(payload["content"])
