"""Run document processing and adjudication as one claim workflow."""

from datetime import date
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import autopsy_sdk as autopsy
from app import faults
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adjudication.models import AdjudicationResult
from app.adjudication.schemas import AdjudicationInputMissing, Decision
from app.adjudication.service import RULES_VERSION, adjudicate_claim
from app.claim_document_intake.models import ClaimDocument, IntakeClaim
from app.document_processing.claim_service import claim_document_processing_service
from app.document_processing.models import ProcessedDocument, ProcessingRun, SemanticArtifact
from app.document_processing.schemas import ProcessClaimResponse
from app.final_result.service import apply_final_result
from app.orchestrator.schemas import ClaimRunResponse


class AdjudicationReplayConflict(RuntimeError):
    """The persisted document run is being replayed with changed business inputs."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)


def _json_default(value: Any):
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported checksum value: {type(value).__name__}")


def _inputs_checksum(claim_form: dict, policy: dict, proofs: list[dict]) -> str:
    encoded = _canonical_json({"claim_form": claim_form, "policy_facts": policy, "proof_facts": proofs}).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact(db: Session, processed: ProcessedDocument, kind: str):
    return db.query(SemanticArtifact).filter_by(processed_document_id=processed.id, artifact_kind=kind).one_or_none()


def _accepted_facts(db: Session, run: ProcessingRun, claim_id: str, claim_docs: list[ClaimDocument]):
    attempts = (db.query(ProcessedDocument).filter_by(run_id=run.id, claim_id=claim_id)
                .order_by(ProcessedDocument.attempt_number.desc(), ProcessedDocument.started_at.desc()).all())
    latest = {}
    for processed in attempts:
        latest.setdefault(processed.intake_document_id, processed)

    accepted: dict[str, dict] = {}
    for document in claim_docs:
        intake_id = document.id
        processed = latest.get(intake_id)
        if processed is None:
            continue
        if (processed.role != document.document_type
                or processed.status not in {"COMPLETED", "VALIDATING"}
                or processed.disposition != "ACCEPTED" or not document.checksum_sha256
                or processed.checksum_sha256 != document.checksum_sha256):
            continue
        classification = _artifact(db, processed, "classification")
        extraction = _artifact(db, processed, "extraction")
        validation = _artifact(db, processed, "application_validation")
        artifacts = (classification, extraction, validation)
        if any(artifact is None for artifact in artifacts):
            continue
        if any(artifact.claim_id != claim_id or artifact.document_id != processed.document_id
               or artifact.input_checksum_sha256 != document.checksum_sha256 for artifact in artifacts):
            continue
        classification_payload = classification.payload if isinstance(classification.payload, dict) else {}
        facts_payload = extraction.payload if isinstance(extraction.payload, dict) else {}
        validation_payload = validation.payload if isinstance(validation.payload, dict) else {}
        if (classification.status != "accepted" or classification_payload.get("disposition") != "accepted"
                or extraction.status != "complete" or validation.status != "passed"
                or facts_payload.get("detected_type") != document.document_type
                or facts_payload.get("document_type") != document.document_type
                or validation_payload.get("status") != "accepted"
                or not isinstance(facts_payload.get("facts"), list)):
            continue
        accepted[str(intake_id)] = {
            "document_id": str(intake_id),
            "document_type": document.document_type,
            "facts": facts_payload["facts"],
        }
    return accepted


def _stored_decision(record: AdjudicationResult) -> Decision:
    return Decision(
        decision=record.decision,
        rules_version=record.rules_version,
        payable_amount=record.payable_amount,
        rules=record.rules,
    )


def _record_decision_and_final_result(decision: Decision, claim_result, *, rules_input_complete=True):
    """Emit the decision boundary and the independently checkable final artifact."""
    decision_payload = decision.model_dump(mode="json")
    decision_upload = {
        "decision": decision.decision,
        "rules_version": decision.rules_version,
        "rules": [
            {key: rule[key] for key in ("rule_id", "result", "consequence", "reason_code")
             if rule.get(key) is not None}
            for rule in decision_payload.get("rules", [])
        ],
    }
    with autopsy.stage("adjudication") as adjudication_stage:
        decision_id = adjudication_stage.record_artifact(
            "decision", decision_payload,
            upload_content=decision_upload, upload_redaction="fields",
        )
        adjudication_stage.set_attribute("pipeline.stage.version", decision.rules_version)
        adjudication_stage.check(
            "rules.input_complete", kind="schema",
            result="pass" if rules_input_complete else "fail",
            action="continued" if rules_input_complete else "blocked",
            observed="accepted_policy_and_proof" if rules_input_complete else "missing_policy_or_proof",
            expected="accepted_policy_and_proof",
        )
        for rule in decision_payload.get("rules", []):
            adjudication_stage.check(
                rule["rule_id"], kind="decision_rule",
                result={"pass": "pass", "fail": "fail", "not_evaluable": "skip"}[rule["result"]],
                action="continued",
                field=next((ref.get("field") for ref in rule.get("inputs", []) if ref.get("field")), None),
                observed=rule["reason_code"] or rule["result"], expected="pass",
            )

    result_payload = claim_result.model_dump(mode="json")
    result_upload = {
        key: result_payload.get(key)
        for key in ("decision", "payable_amount", "message_code")
    }
    matches = result_payload.get("decision") == decision_payload.get("decision")
    with autopsy.stage("final_result", inputs=[decision_id]) as final_stage:
        result_id = final_stage.record_artifact(
            "claim_result", result_payload,
            upload_content=result_upload, upload_redaction="fields",
        )
        final_stage.check(
            "final.matches_decision", kind="rule",
            result="pass" if matches else "fail", action="continued",
            target=result_id, field="decision",
            observed=result_payload.get("decision"), expected=decision_payload.get("decision"),
        )
    return decision_id, result_id


class ClaimRunService:
    def __init__(self, document_service=claim_document_processing_service):
        self.document_service = document_service

    def process_claim(self, db: Session, claim_id: str, config_version: str,
                      *, fault: str | None = None) -> ClaimRunResponse:
        claim = db.query(IntakeClaim).filter_by(claim_id=claim_id).one_or_none()
        if claim is None:
            processing = self.document_service.process_claim(db, claim_id, config_version)
            return self._process_claim_result(db, claim_id, processing)
        documents = db.query(ClaimDocument).filter_by(claim_id=claim_id).order_by(ClaimDocument.document_slot).all()
        items = {
            str(document.id): "policy" if document.document_type == "policy_document" else "proof"
            for document in documents
        }
        provisional_run_id = uuid4()
        with autopsy.run(entity_id=claim.id, run_id=provisional_run_id, items=items, trigger="api") as trace_run:
            if fault:
                trace_run.set_attribute("pipeline.fault.name", fault)
            processing = self.document_service.process_claim(
                db, claim_id,
                f"{config_version}|fault={fault}" if fault else config_version,
                run_id=provisional_run_id,
            )
            if processing.run_id:
                trace_run.set_run_id(processing.run_id)
            response = self._process_claim_result(db, claim_id, processing)
            outcome = {
                "COMPLETED": "success", "PARTIAL": "partial", "BLOCKED": "blocked",
                "FAILED": "failed", "REVIEW_REQUIRED": "partial",
            }.get(response.status, "failed")
            trace_run.set_outcome(outcome)
            return response

    def _process_claim_result(self, db: Session, claim_id: str, processing: ProcessClaimResponse) -> ClaimRunResponse:
        if not processing.run_id:
            return ClaimRunResponse(
                run_id="", claim_id=claim_id, status=processing.status,
                policy_document_id=processing.policy_document_id,
                proof_document_ids=processing.proof_document_ids,
                failed_document_ids=processing.failed_document_ids, error=processing.error,
            )

        run = db.query(ProcessingRun).filter_by(id=UUID(processing.run_id), claim_id=claim_id).one_or_none()
        claim = db.query(IntakeClaim).filter_by(claim_id=claim_id).one_or_none()
        if run is None or claim is None:
            return ClaimRunResponse(run_id=processing.run_id, claim_id=claim_id,
                status="FAILED", error="The processing run could not be loaded.")
        if run.status not in {"COMPLETED", "PARTIAL"}:
            response_status = "BLOCKED" if not self._has_accepted_policy(db, run, claim) else run.status
            return self._response(processing, response_status, error=run.error)

        documents = db.query(ClaimDocument).filter_by(claim_id=claim_id).order_by(ClaimDocument.document_slot).all()
        accepted = _accepted_facts(db, run, claim_id, documents)
        policy = next((item for item in accepted.values() if item["document_type"] == "policy_document"), None)
        if policy is None:
            return self._response(processing, "BLOCKED", error="Policy facts were not accepted; adjudication was not run.")
        proofs = [item for item in accepted.values() if item["document_type"] != "policy_document"]
        claim_form = {
            "document_id": "claim_form",
            "policy_number": claim.policy_number,
            "policyholder_name": claim.policyholder_name,
            "incident_date": claim.incident_date,
            "claimed_amount": claim.claimed_amount,
        }
        checksum = _inputs_checksum(claim_form, policy, proofs)
        stored = db.query(AdjudicationResult).filter_by(run_id=run.id).one_or_none()
        if stored is not None:
            if stored.inputs_checksum != checksum:
                raise AdjudicationReplayConflict("The run already has a decision for different inputs; use a new config_version.")
            decision = _stored_decision(stored)
            final_decision = faults.after_adjudication(decision)
            claim_result = apply_final_result(db, claim, final_decision, run_id=processing.run_id)
            _record_decision_and_final_result(decision, claim_result)
            return self._response(processing, processing.status, decision=final_decision)

        try:
            decision = adjudicate_claim(claim_form, policy, proofs)
        except AdjudicationInputMissing as exc:
            with autopsy.stage("adjudication") as stage:
                stage.check(
                    # Missing accepted inputs usually reflect an upstream gate.
                    # Keep this as a warning so the missing producer remains the origin.
                    "rules.input_complete", kind="schema", result="warn", action="review",
                    observed=exc.missing_kind, expected="accepted_policy_and_proof",
                )
            return self._response(processing, "BLOCKED", error=str(exc))

        record = AdjudicationResult(
            run_id=run.id, claim_id=claim_id, rules_version=RULES_VERSION,
            decision=decision.decision, payable_amount=decision.payable_amount,
            rules=[rule.model_dump(mode="json") for rule in decision.rules], inputs_checksum=checksum,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            stored = db.query(AdjudicationResult).filter_by(run_id=run.id).one_or_none()
            if stored is None or stored.inputs_checksum != checksum:
                raise AdjudicationReplayConflict("The run already has a decision for different inputs; use a new config_version.")
            decision = _stored_decision(stored)
        final_decision = faults.after_adjudication(decision)
        claim_result = apply_final_result(db, claim, final_decision, run_id=processing.run_id)
        _record_decision_and_final_result(decision, claim_result)
        return self._response(processing, processing.status, decision=final_decision)

    @staticmethod
    def _has_accepted_policy(db: Session, run: ProcessingRun, claim: IntakeClaim) -> bool:
        documents = db.query(ClaimDocument).filter_by(claim_id=claim.claim_id, document_type="policy_document").all()
        accepted = _accepted_facts(db, run, claim.claim_id, documents)
        return any(item["document_type"] == "policy_document" for item in accepted.values())

    @staticmethod
    def _response(processing, status, *, decision=None, error=None):
        return ClaimRunResponse(
            run_id=processing.run_id, claim_id=processing.claim_id, status=status,
            policy_document_id=processing.policy_document_id,
            proof_document_ids=processing.proof_document_ids,
            failed_document_ids=processing.failed_document_ids,
            decision=decision, error=error if error is not None else processing.error,
        )


claim_run_service = ClaimRunService()
