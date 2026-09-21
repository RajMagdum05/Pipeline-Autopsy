from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from autopsy.services.reconstruction_service import ExecutionGraph, PipelineReconstructionEngine
from autopsy.services.failure_detection_service import FailureDetectionService
from autopsy.services.root_cause_service import (
    RootCauseAnalysisEngine,
    RootCauseAnalysisResult,
    RootCauseCandidate,
)
from autopsy.detectors.finding import Finding
from autopsy.db.models import FailureModel, EvidenceModel, ExecutionModel, IncidentModel


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


class AutopsyDiagnosisSchema(BaseModel):
    """Pydantic schema for structured output validation from LLM or deterministic builder."""
    summary: str = Field(description="Concise engineering summary of the incident and observed failure")
    affected_component: str = Field(description="Primary service and operation component where failure originated")
    observed_failure: str = Field(description="Direct failure symptom or exception observed in telemetry")
    root_cause_candidate: str = Field(description="Identified root-cause candidate component and rationale")
    supporting_evidence: List[str] = Field(description="List of factual telemetry evidence points referencing spans/events")
    downstream_impact: List[str] = Field(description="List of downstream services or operations impacted by this failure")
    uncertainty: str = Field(description="Uncertainty state: SUPPORTED_BY_EVIDENCE, POSSIBLE, or INSUFFICIENT_EVIDENCE")
    suggested_investigation: List[str] = Field(description="Actionable steps for engineers to debug or remediate the issue")


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


class EvidenceAggregator:
    """
    Aggregates and filters relevant telemetry, failure records, and RCA findings into a clean DiagnosisContext.
    """

    def aggregate(
        self,
        graph: ExecutionGraph,
        findings: List[Finding],
        rca_result: RootCauseAnalysisResult,
    ) -> DiagnosisContext:
        affected_comps = []
        evidence_list = []
        downstream_list = []

        seen_spans = set()
        for f in findings:
            if f.span_id and f.span_id not in seen_spans:
                seen_spans.add(f.span_id)
                affected_comps.append({
                    "span_id": f.span_id,
                    "service_name": f.service_name,
                    "operation_name": f.operation_name,
                    "severity": f.severity,
                    "finding_type": f.finding_type,
                })

            evidence_list.append({
                "detector": f.detector_name,
                "evidence_type": f.evidence_type,
                "span_id": f.span_id,
                "service_name": f.service_name,
                "operation_name": f.operation_name,
                "description": f.description,
                "evidence_data": f.evidence_data,
            })

        for cand in rca_result.candidates:
            for ds in cand.downstream_impact_spans:
                downstream_list.append(ds)

        timing_data = {
            "start_time": graph.start_time.isoformat() if graph.start_time else None,
            "end_time": graph.end_time.isoformat() if graph.end_time else None,
            "duration_ms": graph.duration_ms,
            "total_spans": graph.total_spans_count,
        }

        return DiagnosisContext(
            execution_id=graph.execution_id,
            trace_id=graph.trace_id,
            pipeline_name=graph.root_nodes[0].service_name if graph.root_nodes else "unknown_pipeline",
            root_cause_candidates=[c.to_dict() for c in rca_result.candidates],
            affected_components=affected_comps,
            supporting_evidence=evidence_list,
            downstream_impact=downstream_list,
            structural_warnings=graph.warnings,
            timing_summary=timing_data,
            unresolved_failures=rca_result.unresolved_failures,
        )


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


AUTOPSY_DIAGNOSIS_PROMPT_V1 = """You are the Pipeline Autopsy Diagnostic Reasoning Engine.
Your task is to analyze the provided deterministic DiagnosisContext JSON and synthesize a concise, factual engineering diagnosis.

CRITICAL CONSTRAINTS:
1. Ground every statement strictly in the provided DiagnosisContext.
2. Do NOT invent components, services, spans, errors, or telemetry.
3. Preserve exact service names, operation names, and span IDs.
4. Clearly distinguish observed facts from inferences.
5. If evidence is ambiguous or multiple parallel candidates exist, declare uncertainty explicitly.
6. Do NOT reveal secrets or credentials.

You must return output adhering to the requested JSON schema.
"""


class LLMDiagnosisService:
    """
    Isolated LLM Diagnosis Reasoning Service using Google Gemini (gemini-1.5-flash / gemini-2.5-flash).
    Receives only sanitized DiagnosisContext. Never interacts directly with database.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def validate_consistency(self, diagnosis: AutopsyDiagnosisSchema, ctx: DiagnosisContext) -> bool:
        """
        Validates that Gemini's structured response does not contradict deterministic telemetry findings.
        Rule: Gemini cannot claim success or hallucinate unobserved services when failures exist.
        """
        summary_lower = diagnosis.summary.lower()
        if ctx.affected_components:
            # If deterministic detectors captured failures, Gemini must not claim no errors occurred
            if "success" in summary_lower and "no errors" in summary_lower and "no failure" in summary_lower:
                print("[WARN] Gemini output contradicted deterministic findings: claimed success despite telemetry failures.")
                return False

        if ctx.root_cause_candidates:
            known_services = {c["service_name"].lower() for c in ctx.root_cause_candidates}
            for comp in ctx.affected_components:
                known_services.add(comp["service_name"].lower())
            
            # Check if affected_component or root_cause_candidate references at least one known service or acknowledges uncertainty
            diag_text = (diagnosis.affected_component + " " + diagnosis.root_cause_candidate + " " + diagnosis.summary).lower()
            matches_known = any(svc in diag_text for svc in known_services)
            if not matches_known and diagnosis.uncertainty not in ("INSUFFICIENT_EVIDENCE", "POSSIBLE"):
                print("[WARN] Gemini output identified an unknown component not grounded in telemetry findings.")
                return False

        return True

    def diagnose_with_llm(self, ctx: DiagnosisContext) -> Optional[AutopsyDiagnosis]:
        """
        Sends DiagnosisContext to Gemini with structured output validation and deterministic consistency checking.
        Returns AutopsyDiagnosis or None if generation/validation/consistency fails.
        """
        if not self.is_available():
            return None

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            context_json = json.dumps(ctx.to_dict(), indent=2)
            prompt = f"DiagnosisContext Data:\n{context_json}"

            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=AUTOPSY_DIAGNOSIS_PROMPT_V1,
                    response_mime_type="application/json",
                    response_schema=AutopsyDiagnosisSchema,
                    temperature=0.1,
                ),
            )

            raw_text = response.text
            if not raw_text:
                return None

            parsed_data = json.loads(raw_text)
            # Validate schema
            validated = AutopsyDiagnosisSchema(**parsed_data)

            # Consistency check against deterministic facts
            if not self.validate_consistency(validated, ctx):
                return None

            return AutopsyDiagnosis(
                execution_id=ctx.execution_id,
                trace_id=ctx.trace_id,
                summary=validated.summary,
                affected_component=validated.affected_component,
                observed_failure=validated.observed_failure,
                root_cause_candidate=validated.root_cause_candidate,
                supporting_evidence=validated.supporting_evidence,
                downstream_impact=validated.downstream_impact,
                uncertainty=validated.uncertainty,
                suggested_investigation=validated.suggested_investigation,
                reasoning_source="LLM_REASONING_LAYER",
            )
        except Exception as err:
            print(f"[WARN] LLM diagnosis failed, gracefully falling back: {err}")
            return None


class DiagnosisService:
    """
    Unified Diagnosis Orchestrator.
    Combines EvidenceAggregator, DeterministicDiagnosisBuilder, and optional LLMDiagnosisService with automatic fallback.
    """

    def __init__(self, llm_service: Optional[LLMDiagnosisService] = None):
        self.aggregator = EvidenceAggregator()
        self.deterministic_builder = DeterministicDiagnosisBuilder()
        self.llm_service = llm_service or LLMDiagnosisService()
        self.recon_engine = PipelineReconstructionEngine()
        self.fail_service = FailureDetectionService()
        self.rca_engine = RootCauseAnalysisEngine()

    def generate_diagnosis(
        self,
        graph: ExecutionGraph,
        findings: List[Finding],
        rca_result: RootCauseAnalysisResult,
        use_llm: bool = True,
    ) -> AutopsyDiagnosis:
        # Step 1: Aggregate evidence into DiagnosisContext
        ctx = self.aggregator.aggregate(graph, findings, rca_result)

        # Step 2: Try LLM reasoning layer if requested and available
        if use_llm and self.llm_service.is_available():
            try:
                llm_diagnosis = self.llm_service.diagnose_with_llm(ctx)
                if llm_diagnosis:
                    return llm_diagnosis
            except Exception as err:
                print(f"[WARN] LLM diagnosis invocation failed, falling back: {err}")

        # Step 3: Fallback to Deterministic Diagnosis Builder
        return self.deterministic_builder.build(ctx)

    def diagnose_and_persist_from_db(
        self, trace_id: str, db: Session, use_llm: bool = True
    ) -> Dict[str, Any]:
        """
        Runs full pipeline from PostgreSQL trace, generates diagnosis, and persists IncidentModel in DB.
        """
        graph = self.recon_engine.reconstruct_from_db(trace_id, db)
        self.fail_service.process_and_persist_failures(graph, db)

        raw_findings = self.fail_service.run_detection(graph)
        failures_db = db.query(FailureModel).filter_by(trace_id=trace_id).all()
        rca_result = self.rca_engine.analyze(graph, raw_findings, failures_db)

        diagnosis = self.generate_diagnosis(graph, raw_findings, rca_result, use_llm=use_llm)

        # Create or update IncidentModel in PostgreSQL
        if failures_db or rca_result.candidates:
            incident = db.query(IncidentModel).filter_by(execution_id=graph.execution_id).first()
            if not incident:
                incident = IncidentModel(
                    execution_id=graph.execution_id,
                    title=f"Incident: {diagnosis.observed_failure} in {diagnosis.affected_component}",
                    status="OPEN",
                    severity="HIGH" if diagnosis.uncertainty != "INSUFFICIENT_EVIDENCE" else "MEDIUM",
                    summary=diagnosis.summary,
                    failure_ids=[f.id for f in failures_db],
                    diagnosis_reference=f"autopsy://diagnosis/{diagnosis.diagnosis_id}",
                    metadata_json=diagnosis.to_dict(),
                )
                db.add(incident)
            else:
                incident.summary = diagnosis.summary
                incident.metadata_json = diagnosis.to_dict()

        # Update ExecutionModel
        exec_rec = db.query(ExecutionModel).filter_by(id=graph.execution_id).first()
        if exec_rec:
            updated_attrs = dict(exec_rec.attributes or {})
            updated_attrs["diagnosis"] = diagnosis.to_dict()
            exec_rec.attributes = updated_attrs

        db.commit()
        return diagnosis.to_dict()
