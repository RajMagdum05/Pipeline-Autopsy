"""Database job scheduling and diagnosis result persistence."""
import hashlib
import traceback
import uuid
from datetime import datetime, timezone

from autopsy.core.fanout import diagnose
from autopsy.core_adapter import build_core_inputs, missing_referenced_artifacts
from autopsy.explain.bundle import build_bundle
from autopsy.explain.llm import client_from_env
from autopsy.explain.service import explain
from autopsy.knowledge.playbooks import retrieve
from autopsy.db.models import (
    DiagnosisJobRecord, ExecutionRecord, ExplanationRecord, FindingRecord,
    ObservationRecord, PipelineRecord,
)


def _finding_stage(stage_name):
    if not stage_name or "@" not in stage_name:
        return stage_name, None
    return tuple(stage_name.split("@", 1))


def _signature(pipeline, stage, classification, evidence, observations):
    evidence_codes = sorted({observations[obs_id].code for obs_id in evidence if obs_id in observations})
    raw = "\0".join((pipeline, stage or "", classification or "", "\0".join(evidence_codes)))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def schedule_diagnosis(db, execution, *, has_run_span, last_span_at, now=None):
    """Create or refresh an execution's diagnosis schedule during ingestion."""
    import os
    from datetime import timedelta

    now = now or datetime.now(timezone.utc)
    if has_run_span:
        run_after = now + timedelta(seconds=float(os.getenv("AUTOPSY_SETTLE_SECONDS", "5")))
        reason = "complete"
    else:
        timeout = float(os.getenv("AUTOPSY_INCOMPLETE_TIMEOUT_SECONDS", "600"))
        run_after = last_span_at + timedelta(seconds=timeout)
        reason = "timeout"

    job = db.get(DiagnosisJobRecord, execution.id)
    if job is None:
        job = DiagnosisJobRecord(execution_id=execution.id, status="pending", attempt=0)
        db.add(job)
    elif job.status == "running":
        return
    job.status = "pending"
    job.reason = reason
    job.run_after = run_after
    job.attempt = 0
    job.error = None
    job.updated_at = now
    execution.status = "queued"


def _persist_result(db, execution, job, result, now, *, artifacts=None, evidence_level="E1", spans=None,
                    llm_client=None):
    bundle = build_bundle(result, artifacts or {}, evidence_level=evidence_level)
    bundle["remediation"] = retrieve(db, bundle["findings"], spans or [])
    # Release the write transaction (playbook sync) before the optional, slow LLM call.
    db.commit()
    explanation = explain(bundle, llm_client)

    db.query(ObservationRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)
    db.query(FindingRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)

    observation_index = {}
    for observation in result.get("observations", []):
        row = ObservationRecord(
            execution_id=execution.id,
            id=observation.id,
            family=observation.family,
            code=observation.code,
            result=observation.result,
            stage=observation.stage,
            span_id=observation.span_id,
            artifact_id=observation.artifact_id,
            field=observation.field,
            reported_by=observation.reported_by,
            error_class=observation.error_class,
            source_artifact_id=observation.source_artifact_id,
            detail=observation.detail,
        )
        db.add(row)
        observation_index[row.id] = row

    for finding in result.get("findings", []):
        stage, item_id = _finding_stage(finding.get("stage"))
        db.add(FindingRecord(
            id=str(uuid.uuid4()),
            execution_id=execution.id,
            stage=stage,
            item_id=item_id,
            role=finding.get("role", "healthy"),
            classification=finding.get("classification"),
            confidence=finding.get("confidence"),
            severity=finding.get("severity"),
            link=finding.get("link"),
            caused_by=finding.get("caused_by", []),
            evidence=finding.get("evidence", []),
            note=finding.get("note"),
            signature=_signature(execution.pipeline, stage, finding.get("classification"),
                                 finding.get("evidence", []), observation_index),
        ))

    explanation_row = db.get(ExplanationRecord, execution.id)
    if explanation_row is None:
        explanation_row = ExplanationRecord(execution_id=execution.id)
        db.add(explanation_row)
    explanation_row.source = explanation["source"]
    explanation_row.summary = explanation["summary"]
    explanation_row.narrative = explanation["narrative"]
    explanation_row.remediation = explanation["remediation"]
    explanation_row.guardrail_log = explanation["guardrail_log"]
    explanation_row.model = explanation["model"]
    explanation_row.tokens_in = explanation["tokens_in"]
    explanation_row.tokens_out = explanation["tokens_out"]
    explanation_row.latency_ms = explanation["latency_ms"]

    execution.verdict = result.get("verdict")
    execution.trace_grade = result.get("trace_grade")
    execution.status = "diagnosed"
    execution.diagnosed_at = now
    job.status = "done"
    job.error = None
    job.updated_at = now
    db.commit()


def _llm_client(factory):
    """Build the optional explanation client; a broken LLM config never fails diagnosis."""
    if factory is None:
        return None
    try:
        return factory()
    except Exception:
        return None


def _mark_unregistered(db, execution, job, now):
    execution.status = "unregistered"
    execution.verdict = None
    execution.trace_grade = None
    execution.diagnosed_at = None
    job.status = "done"
    job.error = None
    job.updated_at = now
    db.commit()


def process_due_jobs(session_factory, *, now=None, settle_seconds=None, incomplete_timeout_seconds=None,
                     llm_client_factory=client_from_env):
    """Run due diagnosis jobs; return the number claimed for processing."""
    import os
    from datetime import timedelta

    now = now or datetime.now(timezone.utc)
    settle_seconds = settle_seconds if settle_seconds is not None else float(os.getenv("AUTOPSY_SETTLE_SECONDS", "5"))
    incomplete_timeout_seconds = (incomplete_timeout_seconds if incomplete_timeout_seconds is not None
                                  else float(os.getenv("AUTOPSY_INCOMPLETE_TIMEOUT_SECONDS", "600")))
    processed = 0
    with session_factory() as db:
        jobs = (
            db.query(DiagnosisJobRecord)
            .filter(DiagnosisJobRecord.status == "pending", DiagnosisJobRecord.run_after <= now)
            .order_by(DiagnosisJobRecord.run_after)
            .all()
        )
        for job in jobs:
            job.status = "running"
            job.updated_at = now
            db.commit()
            processed += 1
            execution = db.get(ExecutionRecord, job.execution_id)
            if execution is None:
                job.status = "failed"
                job.error = "Execution record not found"
                job.updated_at = now
                db.commit()
                continue
            pipeline = db.get(PipelineRecord, (execution.project_id, execution.pipeline, execution.version))
            if pipeline is None or not pipeline.manifest or not pipeline.manifest.get("stages"):
                _mark_unregistered(db, execution, job, now)
                continue
            try:
                spans, artifacts, manifest, items = build_core_inputs(db, execution, pipeline)
                missing = missing_referenced_artifacts(spans, artifacts)
                if pipeline.evidence_level == "E2" and missing and job.attempt < 1:
                    job.status = "pending"
                    job.attempt += 1
                    job.run_after = now + timedelta(seconds=30)
                    job.updated_at = now
                    db.commit()
                    continue
                result = diagnose(spans, artifacts, manifest, items if items else None)
                _persist_result(
                    db, execution, job, result, now,
                    artifacts=artifacts, evidence_level=pipeline.evidence_level or "E1",
                    spans=spans,
                    llm_client=_llm_client(llm_client_factory),
                )
            except Exception:
                db.rollback()
                current_job = db.get(DiagnosisJobRecord, job.execution_id)
                current_execution = db.get(ExecutionRecord, job.execution_id)
                if current_job is not None:
                    current_job.status = "failed"
                    current_job.error = traceback.format_exc()
                    current_job.updated_at = now
                if current_execution is not None:
                    current_execution.status = "failed"
                db.commit()
    return processed
