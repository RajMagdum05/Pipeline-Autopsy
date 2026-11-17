from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.orm import Session

from autopsy.services.reconstruction_service import ExecutionGraph, ExecutionNode, PipelineReconstructionEngine
from autopsy.services.failure_detection_service import FailureDetectionService
from autopsy.detectors.finding import Finding
from autopsy.db.models import FailureModel, EvidenceModel, ExecutionModel


def _gen_uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class RootCauseCandidate:
    """
    Internal normalized representation of a root-cause candidate.
    """
    execution_id: str
    trace_id: str
    span_id: str
    service_name: str
    operation_name: str
    confidence_state: str  # supported, possible, insufficient_evidence
    relationship_type: str  # DIRECT_FAILURE, UPSTREAM_DEPENDENCY_PROPAGATION, INDEPENDENT_PARALLEL_FAILURE, UNRESOLVED_TIMING
    reason: str
    failure_id: Optional[str] = None
    supporting_evidence: List[Dict[str, Any]] = field(default_factory=list)
    downstream_impact_spans: List[Dict[str, Any]] = field(default_factory=list)
    candidate_id: str = field(default_factory=_gen_uuid)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "failure_id": self.failure_id,
            "span_id": self.span_id,
            "service_name": self.service_name,
            "operation_name": self.operation_name,
            "confidence_state": self.confidence_state,
            "relationship_type": self.relationship_type,
            "reason": self.reason,
            "supporting_evidence": self.supporting_evidence,
            "downstream_impact_spans": self.downstream_impact_spans,
        }


@dataclass
class RootCauseAnalysisResult:
    """
    Container for complete Root Cause Analysis results.
    """
    execution_id: str
    trace_id: str
    analysis_status: str  # ROOT_CAUSE_IDENTIFIED, MULTIPLE_CANDIDATES, INSUFFICIENT_EVIDENCE, NO_FAILURES
    candidates: List[RootCauseCandidate] = field(default_factory=list)
    unresolved_failures: List[Dict[str, Any]] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "analysis_status": self.analysis_status,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "unresolved_failures": self.unresolved_failures,
        }


class RootCauseAnalysisEngine:
    """
    Deterministic Evidence-Based Root Cause Analysis Engine.

    Maps detected failures onto reconstructed execution graphs using parent-child topology,
    timestamp precedence, and explicit failure propagation evidence. Zero LLMs or domain guesswork.
    """

    def analyze(
        self,
        graph: ExecutionGraph,
        findings: List[Finding],
        failures_db: Optional[List[Any]] = None,
    ) -> RootCauseAnalysisResult:
        """
        Analyzes an ExecutionGraph and its findings/failures to determine root-cause candidates.
        """
        result = RootCauseAnalysisResult(
            execution_id=graph.execution_id, trace_id=graph.trace_id, analysis_status="NO_FAILURES"
        )

        if not findings and not failures_db:
            return result

        # 1. Build lookup maps from ExecutionGraph
        nodes_by_span_id: Dict[str, ExecutionNode] = {}

        def index_nodes(node: ExecutionNode):
            nodes_by_span_id[node.span_id] = node
            for child in node.children:
                index_nodes(child)

        for root in graph.root_nodes:
            index_nodes(root)
        for orphan in graph.orphan_nodes:
            index_nodes(orphan)

        # 2. Group findings by span ID
        findings_by_span: Dict[str, List[Finding]] = {}
        for f in findings:
            if f.span_id:
                findings_by_span.setdefault(f.span_id, []).append(f)

        DIRECT_FAILURE_TYPES = {"SPAN_ERROR_STATUS", "EXCEPTION_EVENT", "TIMEOUT_EXCEEDED", "EXPLICIT_VALIDATION_FAILURE"}

        # Spans that experienced direct operational failures
        direct_failed_span_ids = {
            s_id for s_id, f_list in findings_by_span.items()
            if any(f.finding_type in DIRECT_FAILURE_TYPES for f in f_list)
        }

        # If no direct failure types found, check any finding
        if not direct_failed_span_ids and findings_by_span:
            direct_failed_span_ids = set(findings_by_span.keys())

        if not direct_failed_span_ids:
            result.analysis_status = "INSUFFICIENT_EVIDENCE"
            result.unresolved_failures.append({"reason": "No direct span failure findings detected."})
            return result

        # Helper to check if ancestor_id is an ancestor of target_id
        def is_ancestor_of(ancestor_id: str, target_id: str) -> bool:
            curr = nodes_by_span_id.get(target_id)
            while curr and curr.parent_span_id:
                if curr.parent_span_id == ancestor_id:
                    return True
                curr = nodes_by_span_id.get(curr.parent_span_id)
            return False

        # 3. Analyze direct failed spans for root causes vs downstream impacts
        candidates: List[RootCauseCandidate] = []

        for span_id in direct_failed_span_ids:
            node = nodes_by_span_id.get(span_id)
            if not node:
                continue

            # Check if any ancestor of this span ALSO experienced a direct failure
            direct_failed_ancestors = [
                anc_id for anc_id in direct_failed_span_ids
                if anc_id != span_id and is_ancestor_of(anc_id, span_id)
            ]

            # Check timing conflict: Did any failed ancestor start AFTER this span?
            timing_conflict = False
            for anc_id in direct_failed_ancestors:
                anc_node = nodes_by_span_id.get(anc_id)
                if anc_node and anc_node.start_time and node.start_time:
                    if anc_node.start_time > node.start_time:
                        timing_conflict = True
                        break

            # If node has no failed ancestors (or timing conflict prevents ancestor causality), it's a Root Cause Candidate!
            if not direct_failed_ancestors or timing_conflict:
                # Identify downstream impacted spans (descendants that also failed or were affected)
                downstream_impact = []
                for other_id in set(nodes_by_span_id.keys()) - {span_id}:
                    if is_ancestor_of(span_id, other_id):
                        other_node = nodes_by_span_id.get(other_id)
                        other_findings = findings_by_span.get(other_id, [])
                        if other_node and (other_id in direct_failed_span_ids or other_findings):
                            downstream_impact.append({
                                "span_id": other_node.span_id,
                                "service_name": other_node.service_name,
                                "operation_name": other_node.operation_name,
                                "status_code": other_node.status_code,
                                "findings": [f.description for f in other_findings],
                            })

                # Supporting evidence: Direct findings on this span + dependency findings from upstream callers
                span_findings = findings_by_span.get(span_id, [])
                evidence_items = [
                    {
                        "detector": f.detector_name,
                        "finding_type": f.finding_type,
                        "description": f.description,
                        "evidence_data": f.evidence_data,
                    }
                    for f in span_findings
                ]

                # Include dependency link evidence from upstream caller nodes pointing to this span
                for caller_id, caller_findings in findings_by_span.items():
                    for cf in caller_findings:
                        if cf.finding_type == "DEPENDENCY_FAILURE" and cf.evidence_data.get("failed_dependent_span_id") == span_id:
                            evidence_items.append({
                                "detector": cf.detector_name,
                                "finding_type": cf.finding_type,
                                "description": f"Upstream caller '{cf.operation_name}' reported dependency failure on span '{node.operation_name}'.",
                                "evidence_data": cf.evidence_data,
                            })

                if timing_conflict:
                    confidence = "possible"
                    rel_type = "UNRESOLVED_TIMING"
                    reason_msg = f"Span '{node.operation_name}' ({node.service_name}) failed, but ancestor span failed later in time (timing conflict)."
                elif downstream_impact:
                    confidence = "supported"
                    rel_type = "UPSTREAM_DEPENDENCY_PROPAGATION"
                    reason_msg = f"Span '{node.operation_name}' ({node.service_name}) experienced direct operational failure, propagating downstream to {len(downstream_impact)} operation(s)."
                else:
                    confidence = "supported"
                    rel_type = "DIRECT_FAILURE"
                    reason_msg = f"Span '{node.operation_name}' ({node.service_name}) produced explicit operational failure with no failed upstream dependencies."

                # Find associated failure_id from DB if present
                fail_id = None
                if failures_db:
                    f_match = next((db_f for db_f in failures_db if getattr(db_f, "span_id", None) == span_id), None)
                    if f_match:
                        fail_id = getattr(f_match, "id", None)

                cand = RootCauseCandidate(
                    execution_id=graph.execution_id,
                    trace_id=graph.trace_id,
                    failure_id=fail_id,
                    span_id=span_id,
                    service_name=node.service_name,
                    operation_name=node.operation_name,
                    confidence_state=confidence,
                    relationship_type=rel_type,
                    reason=reason_msg,
                    supporting_evidence=evidence_items,
                    downstream_impact_spans=downstream_impact,
                )
                candidates.append(cand)

        # Set final analysis status
        if len(candidates) == 1:
            result.analysis_status = "ROOT_CAUSE_IDENTIFIED"
        elif len(candidates) > 1:
            result.analysis_status = "MULTIPLE_CANDIDATES"
        else:
            result.analysis_status = "INSUFFICIENT_EVIDENCE"
            result.unresolved_failures.append({
                "reason": "Available telemetry evidence is insufficient to isolate a root-cause candidate."
            })

        result.candidates = candidates
        return result

    def analyze_and_persist_from_db(self, trace_id: str, db: Session) -> Dict[str, Any]:
        """
        Runs full pipeline: reconstructs graph, runs failure detection, calculates root-cause candidates,
        and persists root-cause hypotheses into PostgreSQL FailureModel records.
        """
        recon_engine = PipelineReconstructionEngine()
        graph = recon_engine.reconstruct_from_db(trace_id, db)

        fail_service = FailureDetectionService()
        detection_summary = fail_service.process_and_persist_failures(graph, db)

        raw_findings = fail_service.run_detection(graph)
        failures_db = db.query(FailureModel).filter_by(trace_id=trace_id).all()

        rca_result = self.analyze(graph, raw_findings, failures_db)

        # Update FailureModel.root_cause_hypothesis in PostgreSQL
        for candidate in rca_result.candidates:
            if candidate.failure_id:
                fail_rec = db.query(FailureModel).filter_by(id=candidate.failure_id).first()
                if fail_rec:
                    fail_rec.root_cause_hypothesis = (
                        f"[{candidate.confidence_state.upper()}] Root Cause Candidate: {candidate.service_name}/{candidate.operation_name}. Reason: {candidate.reason}"
                    )
                    fail_rec.attributes["root_cause_candidate"] = candidate.to_dict()

        # Update execution model metadata
        exec_rec = db.query(ExecutionModel).filter_by(id=graph.execution_id).first()
        if exec_rec:
            updated_attrs = dict(exec_rec.attributes or {})
            updated_attrs["root_cause_analysis"] = rca_result.to_dict()
            exec_rec.attributes = updated_attrs

        db.commit()
        return rca_result.to_dict()
