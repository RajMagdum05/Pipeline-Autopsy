from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from autopsy.detectors import (
    Finding,
    BaseDetector,
    ErrorStatusDetector,
    ExceptionDetector,
    TimeoutDetector,
    DependencyFailureDetector,
    StructuralTelemetryDetector,
    ExplicitValidationDetector,
)
from autopsy.services.reconstruction_service import ExecutionGraph, PipelineReconstructionEngine
from autopsy.db.models import FailureModel, EvidenceModel, ExecutionModel


SEVERITY_WEIGHTS = {"INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


class FailureDetectionService:
    """
    Generalized Failure Detection & Correlation Service.

    Executes registered detector suite against an ExecutionGraph, correlates
    multi-signal findings per span/trace into single failure records with distinct evidence,
    and persists FailureModel and EvidenceModel records into PostgreSQL.
    """

    def __init__(self, detectors: Optional[List[BaseDetector]] = None):
        if detectors is not None:
            self.detectors = detectors
        else:
            self.detectors = [
                ErrorStatusDetector(),
                ExceptionDetector(),
                TimeoutDetector(),
                DependencyFailureDetector(),
                StructuralTelemetryDetector(),
                ExplicitValidationDetector(),
            ]
        self.reconstruction_engine = PipelineReconstructionEngine()

    def run_detection(self, graph: ExecutionGraph) -> List[Finding]:
        """Runs all registered detectors against the ExecutionGraph and returns raw findings."""
        raw_findings: List[Finding] = []
        for detector in self.detectors:
            try:
                res = detector.detect(graph)
                raw_findings.extend(res)
            except Exception as err:
                print(f"[ERROR] Detector '{detector.detector_name}' failed: {err}")
        return raw_findings

    def process_and_persist_failures(
        self, graph: ExecutionGraph, db: Session
    ) -> Dict[str, Any]:
        """
        Runs failure detection, correlates multi-signal findings per span, persists
        EvidenceModel and FailureModel records into PostgreSQL, and updates execution status.

        Args:
            graph: ExecutionGraph instance.
            db: Active SQLAlchemy Session.

        Returns:
            Dictionary containing failure detection summary metrics and persisted IDs.
        """
        raw_findings = self.run_detection(graph)

        if not raw_findings:
            return {
                "status": "clean",
                "execution_id": graph.execution_id,
                "trace_id": graph.trace_id,
                "findings_count": 0,
                "failures_persisted": 0,
                "evidence_persisted": 0,
                "failure_ids": [],
            }

        # Step 1: Correlate Findings by Span ID (or finding_type if span_id is None)
        correlated_groups: Dict[str, List[Finding]] = {}
        for f in raw_findings:
            group_key = f.span_id if f.span_id else f"{f.finding_type}_global"
            if group_key not in correlated_groups:
                correlated_groups[group_key] = []
            correlated_groups[group_key].append(f)

        persisted_failures: List[str] = []
        total_evidence = 0
        has_severe_failure = False

        # Step 2: Create EvidenceModel and FailureModel for each correlated group
        for group_key, findings_list in correlated_groups.items():
            # Determine highest severity in group
            highest_sev = max(
                findings_list,
                key=lambda item: SEVERITY_WEIGHTS.get(item.severity.upper(), 1),
            ).severity.upper()

            if highest_sev in ("ERROR", "CRITICAL"):
                has_severe_failure = True

            primary_finding = findings_list[0]
            failure_type = primary_finding.finding_type
            span_id = primary_finding.span_id
            service_name = primary_finding.service_name
            op_name = primary_finding.operation_name

            # Create individual EvidenceModel records for each finding signal
            evidence_ids: List[str] = []
            for f in findings_list:
                ev_rec = EvidenceModel(
                    execution_id=graph.execution_id,
                    trace_id=graph.trace_id,
                    span_id=f.span_id,
                    evidence_type=f.evidence_type,
                    reference_uri=f"autopsy://detectors/{f.detector_name}/{f.finding_id}",
                    summary=f.description,
                    metadata_json={
                        "detector_name": f.detector_name,
                        "finding_type": f.finding_type,
                        "evidence_data": f.evidence_data,
                    },
                )
                db.add(ev_rec)
                db.flush()
                evidence_ids.append(ev_rec.id)
                total_evidence += 1

            # Construct unified failure description from correlated signals
            signal_descriptions = [f.description for f in findings_list]
            unified_desc = (
                f"Failure in operation '{op_name}' ({service_name}) supported by {len(findings_list)} evidence signal(s): "
                + " | ".join(signal_descriptions)
            )

            error_class_val = next(
                (f.evidence_data.get("exception_type") for f in findings_list if f.evidence_data.get("exception_type")),
                None,
            )

            # Create FailureModel record
            failure_rec = FailureModel(
                execution_id=graph.execution_id,
                trace_id=graph.trace_id,
                span_id=span_id,
                failure_type=failure_type,
                severity=highest_sev,
                error_class=error_class_val,
                description=unified_desc,
                evidence_ids=evidence_ids,
                attributes={
                    "service_name": service_name,
                    "operation_name": op_name,
                    "correlated_signals_count": len(findings_list),
                    "detectors": list(set(f.detector_name for f in findings_list)),
                },
            )
            db.add(failure_rec)
            db.flush()
            persisted_failures.append(failure_rec.id)

        # Step 3: Update ExecutionModel status if severe failure occurred
        if has_severe_failure:
            exec_rec = (
                db.query(ExecutionModel)
                .filter(ExecutionModel.id == graph.execution_id)
                .first()
            )
            if exec_rec:
                exec_rec.status = "FAILED"

        db.commit()

        return {
            "status": "failures_detected",
            "execution_id": graph.execution_id,
            "trace_id": graph.trace_id,
            "findings_count": len(raw_findings),
            "failures_persisted": len(persisted_failures),
            "evidence_persisted": total_evidence,
            "failure_ids": persisted_failures,
        }

    def detect_and_persist_from_db(
        self, trace_id: str, db: Session
    ) -> Dict[str, Any]:
        """
        Reconstructs execution graph for a stored trace and runs failure detection & persistence.
        """
        graph = self.reconstruction_engine.reconstruct_from_db(trace_id, db)
        return self.process_and_persist_failures(graph, db)
