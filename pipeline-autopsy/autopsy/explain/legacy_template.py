from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
import uuid

def _gen_uuid() -> str:
    return str(uuid.uuid4())

@dataclass
class DiagnosisContext:
    """
    Sanitized, structured context assembled specifically for diagnosis reasoning.
    """
    execution_id: str
    trace_id: str
    pipeline_name: str
    root_cause_candidates: List[Dict[str, Any]] = field(default_factory=list)
    affected_components: List[Dict[str, Any]] = field(default_factory=list)
    supporting_evidence: List[Dict[str, Any]] = field(default_factory=list)
    downstream_impact: List[Dict[str, Any]] = field(default_factory=list)
    structural_warnings: List[Dict[str, Any]] = field(default_factory=list)
    timing_summary: Dict[str, Any] = field(default_factory=dict)
    unresolved_failures: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "pipeline_name": self.pipeline_name,
            "root_cause_candidates": self.root_cause_candidates,
            "affected_components": self.affected_components,
            "supporting_evidence": self.supporting_evidence,
            "downstream_impact": self.downstream_impact,
            "structural_warnings": self.structural_warnings,
            "timing_summary": self.timing_summary,
            "unresolved_failures": self.unresolved_failures,
        }



@dataclass
class AutopsyDiagnosis:
    """
    Domain model representing the final diagnosis result.
    """
    execution_id: str
    trace_id: str
    summary: str
    affected_component: str
    observed_failure: str
    root_cause_candidate: str
    supporting_evidence: List[str] = field(default_factory=list)
    downstream_impact: List[str] = field(default_factory=list)
    uncertainty: str = "SUPPORTED_BY_EVIDENCE"  # SUPPORTED_BY_EVIDENCE, POSSIBLE, INSUFFICIENT_EVIDENCE
    suggested_investigation: List[str] = field(default_factory=list)
    reasoning_source: str = "DETERMINISTIC_ENGINE"  # DETERMINISTIC_ENGINE, LLM_REASONING_LAYER
    diagnosis_id: str = field(default_factory=_gen_uuid)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diagnosis_id": self.diagnosis_id,
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "summary": self.summary,
            "affected_component": self.affected_component,
            "observed_failure": self.observed_failure,
            "root_cause_candidate": self.root_cause_candidate,
            "supporting_evidence": self.supporting_evidence,
            "downstream_impact": self.downstream_impact,
            "uncertainty": self.uncertainty,
            "suggested_investigation": self.suggested_investigation,
            "reasoning_source": self.reasoning_source,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }



class DeterministicDiagnosisBuilder:
    """
    Constructs a factual, deterministic diagnosis directly from a DiagnosisContext without calling an LLM.
    """

    def build(self, ctx: DiagnosisContext) -> AutopsyDiagnosis:
        if not ctx.root_cause_candidates and not ctx.affected_components:
            return AutopsyDiagnosis(
                execution_id=ctx.execution_id,
                trace_id=ctx.trace_id,
                summary="Execution completed successfully with no observable failures detected in telemetry.",
                affected_component="None",
                observed_failure="None",
                root_cause_candidate="None",
                supporting_evidence=[],
                downstream_impact=[],
                uncertainty="SUPPORTED_BY_EVIDENCE",
                suggested_investigation=["No action required."],
                reasoning_source="DETERMINISTIC_ENGINE",
            )

        if not ctx.root_cause_candidates:
            return AutopsyDiagnosis(
                execution_id=ctx.execution_id,
                trace_id=ctx.trace_id,
                summary="Telemetry recorded failure indicators, but available evidence is insufficient to isolate a root cause.",
                affected_component=", ".join([f"{c['service_name']}/{c['operation_name']}" for c in ctx.affected_components]),
                observed_failure="Unresolved telemetry failure",
                root_cause_candidate="INSUFFICIENT_EVIDENCE",
                supporting_evidence=[e["description"] for e in ctx.supporting_evidence],
                downstream_impact=[],
                uncertainty="INSUFFICIENT_EVIDENCE",
                suggested_investigation=["Inspect individual span error logs and verify telemetry completeness."],
                reasoning_source="DETERMINISTIC_ENGINE",
            )

        # Build from primary candidate (or multiple candidates)
        if len(ctx.root_cause_candidates) == 1:
            cand = ctx.root_cause_candidates[0]
            affected_comp = f"{cand['service_name']}/{cand['operation_name']} (span_id: {cand['span_id']})"
            rc_desc = f"{cand['service_name']}/{cand['operation_name']}: {cand['reason']}"
            uncertainty_state = "SUPPORTED_BY_EVIDENCE" if cand["confidence_state"] == "supported" else "POSSIBLE"

            # Extract observed failure
            primary_ev = cand["supporting_evidence"][0] if cand.get("supporting_evidence") else None
            if primary_ev and isinstance(primary_ev, dict):
                observed_fail = (
                    primary_ev.get("description")
                    or primary_ev.get("details")
                    or primary_ev.get("summary")
                    or primary_ev.get("reason")
                    or "Direct operational error"
                )
            else:
                observed_fail = str(primary_ev) if primary_ev else "Direct operational error"

            summary = (
                f"Execution failed in component '{affected_comp}'. "
                f"Root cause candidate is '{cand['service_name']}/{cand['operation_name']}' ({cand['relationship_type']}). "
                f"Impacted {len(cand.get('downstream_impact_spans', []))} downstream operation(s)."
            )

            evidence_items = []
            for ev in cand.get("supporting_evidence", []):
                if isinstance(ev, dict):
                    desc = ev.get("description") or ev.get("details") or ev.get("summary") or str(ev)
                else:
                    desc = str(ev)
                evidence_items.append(desc)

            downstream_items = [
                f"{ds['operation_name']} ({ds['service_name']}, span_id: {ds['span_id']})"
                for ds in cand.get("downstream_impact_spans", [])
            ]

            investigation = [
                f"Check logs and dependencies for service '{cand['service_name']}', operation '{cand['operation_name']}'.",
                f"Verify downstream consumers: {', '.join([ds['operation_name'] for ds in cand.get('downstream_impact_spans', [])]) or 'None'}.",
            ]

            return AutopsyDiagnosis(
                execution_id=ctx.execution_id,
                trace_id=ctx.trace_id,
                summary=summary,
                affected_component=affected_comp,
                observed_failure=observed_fail,
                root_cause_candidate=rc_desc,
                supporting_evidence=evidence_items,
                downstream_impact=downstream_items,
                uncertainty=uncertainty_state,
                suggested_investigation=investigation,
                reasoning_source="DETERMINISTIC_ENGINE",
            )
        else:
            # Multiple independent candidates
            candidate_names = [f"{c['service_name']}/{c['operation_name']}" for c in ctx.root_cause_candidates]
            summary = (
                f"Execution encountered {len(ctx.root_cause_candidates)} independent failure candidates: "
                + ", ".join(candidate_names)
                + ". Telemetry indicates parallel/unconnected failure origins."
            )
            return AutopsyDiagnosis(
                execution_id=ctx.execution_id,
                trace_id=ctx.trace_id,
                summary=summary,
                affected_component=", ".join(candidate_names),
                observed_failure="Multiple independent operational errors",
                root_cause_candidate="MULTIPLE_INDEPENDENT_CANDIDATES: " + ", ".join(candidate_names),
                supporting_evidence=[e.get("description", str(e)) if isinstance(e, dict) else str(e) for e in ctx.supporting_evidence],
                downstream_impact=[
                    f"{ds.get('operation_name')} ({ds.get('service_name')})" for ds in ctx.downstream_impact
                ],
                uncertainty="POSSIBLE",
                suggested_investigation=[
                    f"Investigate parallel branch failures in services: {', '.join(candidate_names)}.",
                    "Verify shared infrastructure, network routes, or concurrent load conditions.",
                ],
                reasoning_source="DETERMINISTIC_ENGINE",
            )


