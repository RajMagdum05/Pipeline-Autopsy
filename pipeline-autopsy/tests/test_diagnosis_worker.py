import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from autopsy.core.contract import artifact_id
from autopsy.db.database import SessionLocal
from autopsy.db.models import (
    ArtifactRecord, DiagnosisJobRecord, ExecutionRecord, FindingRecord,
    ObservationRecord, PipelineRecord, SpanRecord,
)
from autopsy.main import app
from autopsy.services.ingestion_service import TelemetryIngestionService
from autopsy.worker.jobs import process_due_jobs, schedule_diagnosis


HEADERS = {"X-Autopsy-Api-Key": "autopsy-test-static-key"}


def _process_due():
    return process_due_jobs(SessionLocal, now=datetime.now(timezone.utc) + timedelta(minutes=3))


@pytest.fixture
def client():
    with TestClient(app, headers=HEADERS) as test_client:
        yield test_client


def _simple_manifest(name):
    return {
        "manifest": "pipeline-manifest/1", "pipeline": name, "version": "1.0.0",
        "external_inputs": ["source"],
        "stages": [{"name": "process", "scope": "run", "consumes": ["source"], "produces": ["result"]}],
    }


def _add_span(db, execution_id, span_id, role, attrs, *, parent=None, events=None, status="OK"):
    common = {"pipeline.name": "worker-test", "pipeline.version": "1.0.0",
              "pipeline.run.id": execution_id, "pipeline.span.role": role}
    attrs = {**common, **attrs}
    now = datetime.now(timezone.utc)
    db.add(SpanRecord(
        trace_id=uuid.uuid4().hex, span_id=span_id, execution_id=execution_id,
        parent_span_id=parent, name=role, kind="INTERNAL", role=role,
        stage_name=attrs.get("pipeline.stage.name"), item_id=attrs.get("pipeline.stage.item_id"),
        attempt=attrs.get("pipeline.stage.attempt"), status=status, start_time=now,
        end_time=now, attrs=attrs, events=events or [], links=[], resource={},
        dropped_attributes=0, dropped_events=0,
    ))
    return span_id


def _seed_simple(execution_id, *, manifest=None, root=True):
    name = manifest["pipeline"] if manifest else f"worker_{execution_id.replace('-', '_')}"
    manifest = manifest or _simple_manifest(name)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(PipelineRecord(project_id="default", name=name, version="1.0.0", manifest=manifest,
                              evidence_level=(manifest.get("evidence") or {}).get("level", "E1"),
                              evidence_kinds_allowed=(manifest.get("evidence") or {}).get("kinds_allowed", [])))
        db.add(ExecutionRecord(id=execution_id, project_id="default", pipeline=name, version="1.0.0",
                               trace_ids=[], status="queued", started_at=now))
        if root:
            _add_span(db, execution_id, "root", "execution", {"pipeline.run.items": []})
        _add_span(db, execution_id, "stage", "stage", {
            "pipeline.stage.name": "process", "pipeline.stage.status": "success",
            "pipeline.stage.attempt": 1, "pipeline.artifact.input_ids": [],
            "pipeline.artifact.output_ids": [],
        }, parent="root" if root else None)
        db.add(DiagnosisJobRecord(execution_id=execution_id, status="pending", reason="complete",
                                  run_after=now + timedelta(minutes=2), attempt=0))
        db.commit()
    return manifest


def _add_artifact(db, tmp_path, execution_id, kind, content, item_id=""):
    artifact = artifact_id(content, kind, execution_id, item_id)
    raw = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    directory = tmp_path / execution_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / artifact
    path.write_bytes(raw)
    db.add(ArtifactRecord(id=artifact, execution_id=execution_id, stage="document_processing",
                          item_id=item_id or None, kind=kind, content_type="application/json",
                          size_bytes=len(raw), sha256=uuid.uuid4().hex, blob_path=str(path), redacted=True))
    return artifact


FANOUT_MANIFEST = {
    "manifest": "pipeline-manifest/1", "pipeline": "worker-fanout", "version": "1.0.0",
    "evidence": {"level": "E1", "kinds_allowed": [], "retention_days": 14},
    "external_inputs": ["source_document", "claim_form"],
    "items": {"roles": ["policy", "proof"]},
    "stages": [
        {"name": "document_processing", "scope": "item", "consumes": ["source_document"], "produces": ["page_text"],
         "requires": [{"stage": "extraction_validation", "item_role": "policy"}]},
        {"name": "content_classification", "scope": "item", "consumes": ["page_text"], "produces": ["classification"]},
        {"name": "information_extraction", "scope": "item", "consumes": ["page_text", "classification"], "produces": ["document_facts"]},
        {"name": "extraction_validation", "scope": "item", "consumes": ["document_facts"], "produces": ["validated_facts"]},
        {"name": "adjudication", "scope": "run", "consumes": ["validated_facts", "claim_form"], "produces": ["decision"]},
        {"name": "final_result", "scope": "run", "consumes": ["decision"], "produces": ["claim_result"]},
    ],
    "artifacts": {"document_facts": {"consistency": [
        {"id": "facts.grounded", "validator": "grounded_fields", "source": "page_text", "fields": ["total"]}
    ]}},
}


def _seed_fanout(execution_id, tmp_path):
    now = datetime.now(timezone.utc)
    items = {"pol": "policy", "bill": "proof", "disch": "proof"}
    base = {"pipeline.name": FANOUT_MANIFEST["pipeline"], "pipeline.version": "1.0.0",
            "pipeline.run.id": execution_id}
    spans = []
    artifacts = {}

    def put(kind, content, item):
        aid = artifact_id(content, kind, execution_id, item)
        artifacts[aid] = (kind, content, item or "")
        return aid

    def span(span_id, role, attrs, *, events=None, status="OK"):
        spans.append(SpanRecord(
            trace_id=uuid.uuid4().hex, span_id=span_id, execution_id=execution_id,
            parent_span_id="root" if span_id != "root" else None, name=role, kind="INTERNAL", role=role,
            stage_name=attrs.get("pipeline.stage.name"), item_id=attrs.get("pipeline.stage.item_id"),
            attempt=attrs.get("pipeline.stage.attempt"), status=status, start_time=now, end_time=now,
            attrs={**base, **attrs}, events=events or [], links=[], resource={},
            dropped_attributes=0, dropped_events=0,
        ))

    span("root", "execution", {"pipeline.span.role": "execution",
                                "pipeline.run.items": [f"{item}:{role}" for item, role in items.items()]})
    sequence = 0

    def stage(name, item, inputs, outputs=(), *, status="success", events=None, error_class=None):
        nonlocal sequence
        sequence += 1
        attrs = {"pipeline.span.role": "stage", "pipeline.stage.name": name,
                 "pipeline.stage.status": status, "pipeline.stage.attempt": 1,
                 "pipeline.artifact.input_ids": list(inputs), "pipeline.artifact.output_ids": list(outputs)}
        if item:
            attrs["pipeline.stage.item_id"] = item
            attrs["pipeline.stage.item_role"] = items[item]
        if error_class:
            attrs["pipeline.error.class"] = error_class
            attrs["error.type"] = "CoverageRuleFailed"
        span(f"s{sequence}", "stage", attrs, events=events, status="ERROR" if status == "failed" else "OK")

    for item in items:
        source = put("source_document", {"id": item}, item)
        text = "Admission 2024-03-02. Total 1200 INR." if item == "bill" else "Admission 2025-03-02. Total 1200 INR."
        page = put("page_text", {"text": text}, item)
        checks = ([{"name": "pipeline.check", "attributes": {
            "pipeline.check.id": "ocr.quality", "pipeline.check.result": "warn",
            "pipeline.check.target_artifact_id": page, "pipeline.check.action": "continued"}}] if item == "bill" else [])
        stage("document_processing", item, [source], [page], events=checks)
        classification = put("classification", {"type": "x"}, item)
        stage("content_classification", item, [page], [classification])
        facts = {"admission_date": "2024-03-02" if item == "bill" else "2025-03-02", "total": "1200"}
        facts_id = put("document_facts", facts, item)
        stage("information_extraction", item, [page, classification], [facts_id])
        validated = put("validated_facts", facts, item)
        stage("extraction_validation", item, [facts_id], [validated])

    form = put("claim_form", {"amount": 1200}, "")
    stage("adjudication", None, [*[aid for aid, (kind, _, _) in artifacts.items() if kind == "validated_facts"], form],
          [], status="failed", error_class="data")

    with SessionLocal() as db:
        db.add(PipelineRecord(project_id="default", name=FANOUT_MANIFEST["pipeline"], version="1.0.0",
                              manifest=FANOUT_MANIFEST, evidence_level="E1", evidence_kinds_allowed=[]))
        db.add(ExecutionRecord(id=execution_id, project_id="default", pipeline=FANOUT_MANIFEST["pipeline"],
                               version="1.0.0", trace_ids=[], status="queued", started_at=now))
        db.add_all(spans)
        for kind, content, item in artifacts.values():
            _add_artifact(db, tmp_path, execution_id, kind, content, item)
        db.add(DiagnosisJobRecord(execution_id=execution_id, status="pending", reason="complete",
                                  run_after=now + timedelta(minutes=2), attempt=0))
        db.commit()


def test_worker_persists_healthy_verdict(client):
    execution_id = f"healthy-{uuid.uuid4().hex[:8]}"
    _seed_simple(execution_id)
    assert _process_due() >= 1
    with SessionLocal() as db:
        execution = db.get(ExecutionRecord, execution_id)
        job = db.get(DiagnosisJobRecord, execution_id)
        assert execution.status == "diagnosed"
        assert execution.verdict == "NO_ISSUE_DETECTED"
        assert execution.trace_grade == "A"
        assert execution.diagnosed_at is not None
        assert job.status == "done"


def test_ingest_schedule_uses_run_settle_and_incomplete_timeout(client, monkeypatch):
    execution_id = f"schedule-{uuid.uuid4().hex[:8]}"
    _seed_simple(execution_id)
    monkeypatch.setenv("AUTOPSY_SETTLE_SECONDS", "5")
    monkeypatch.setenv("AUTOPSY_INCOMPLETE_TIMEOUT_SECONDS", "600")
    now = datetime.now(timezone.utc)
    last_span = now - timedelta(seconds=10)
    with SessionLocal() as db:
        execution = db.get(ExecutionRecord, execution_id)
        job = db.get(DiagnosisJobRecord, execution_id)
        schedule_diagnosis(db, execution, has_run_span=True, last_span_at=last_span, now=now)
        assert job.reason == "complete"
        assert job.run_after.replace(tzinfo=timezone.utc) == now + timedelta(seconds=5)
        schedule_diagnosis(db, execution, has_run_span=False, last_span_at=last_span, now=now)
        assert job.reason == "timeout"
        assert job.run_after.replace(tzinfo=timezone.utc) == last_span + timedelta(seconds=600)
        db.commit()


def test_otlp_ingestion_creates_due_diagnosis_job(client, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SETTLE_SECONDS", "5")
    execution_id = f"ingested-{uuid.uuid4().hex[:8]}"
    trace_id, span_id = uuid.uuid4().hex, uuid.uuid4().hex[:16]
    attrs = {
        "pipeline.name": f"ingested_{execution_id.replace('-', '_')}",
        "pipeline.version": "1.0.0", "pipeline.run.id": execution_id,
        "pipeline.span.role": "execution", "pipeline.run.items": [],
    }
    payload = {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "worker-test"}}]},
        "scopeSpans": [{"spans": [{
            "traceId": trace_id, "spanId": span_id, "name": "pipeline.run",
            "startTimeUnixNano": "1700000000000000000", "endTimeUnixNano": "1700000001000000000",
            "attributes": [{"key": key, "value": {"stringValue": value}}
                           for key, value in attrs.items() if key != "pipeline.run.items"]
                           + [{"key": "pipeline.run.items", "value": {"arrayValue": {"values": []}}}],
        }]}],
    }]}
    with SessionLocal() as db:
        result = TelemetryIngestionService().ingest_otlp_payload(payload, db)
        job = db.get(DiagnosisJobRecord, execution_id)
        assert result["status"] == "success"
        assert job.status == "pending" and job.reason == "complete"
        delay = (job.run_after.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        assert 4 <= delay <= 5
        db.delete(job)
        db.delete(db.get(ExecutionRecord, execution_id))
        db.commit()


def test_worker_persists_f2_origin_at_item_stage(client, tmp_path):
    execution_id = f"fanout-{uuid.uuid4().hex[:8]}"
    _seed_fanout(execution_id, tmp_path)
    assert _process_due() == 1
    with SessionLocal() as db:
        findings = db.query(FindingRecord).filter_by(execution_id=execution_id).all()
        origin = next(finding for finding in findings if finding.role == "origin")
        assert origin.stage == "document_processing"
        assert origin.item_id == "bill"
        assert origin.classification == "OUTPUT_CONTRACT_VIOLATION"


def test_grade_c_fixture_returns_insufficient_evidence(client):
    execution_id = f"grade-c-{uuid.uuid4().hex[:8]}"
    _seed_simple(execution_id, root=False)
    assert _process_due() == 1
    with SessionLocal() as db:
        execution = db.get(ExecutionRecord, execution_id)
        assert execution.verdict == "INSUFFICIENT_EVIDENCE"
        assert execution.trace_grade == "C"


def test_missing_e2_artifact_requeues_once_then_completes(client):
    execution_id = f"retry-{uuid.uuid4().hex[:8]}"
    name = f"retry_{uuid.uuid4().hex[:6]}"
    manifest = _simple_manifest(name)
    manifest["evidence"] = {"level": "E2", "kinds_allowed": [], "retention_days": 14}
    _seed_simple(execution_id, manifest=manifest)
    with SessionLocal() as db:
        span = db.query(SpanRecord).filter_by(execution_id=execution_id, span_id="stage").one()
        span.attrs = {**span.attrs, "pipeline.artifact.output_ids": ["art_0123456789abcdef"]}
        db.commit()
    now = datetime.now(timezone.utc) + timedelta(minutes=2)
    assert process_due_jobs(SessionLocal, now=now) == 1
    with SessionLocal() as db:
        job = db.get(DiagnosisJobRecord, execution_id)
        assert job.status == "pending" and job.attempt == 1
        assert job.run_after.replace(tzinfo=timezone.utc) == now + timedelta(seconds=30)
    assert process_due_jobs(SessionLocal, now=now + timedelta(seconds=31)) == 1
    with SessionLocal() as db:
        assert db.get(DiagnosisJobRecord, execution_id).status == "done"
        assert db.query(ObservationRecord).filter_by(execution_id=execution_id, code="artifact_not_found").count() == 1


def test_worker_records_exception_and_continues(client, monkeypatch):
    first, second = f"boom-{uuid.uuid4().hex[:8]}", f"ok-{uuid.uuid4().hex[:8]}"
    _seed_simple(first, manifest=_simple_manifest("boom"))
    _seed_simple(second, manifest=_simple_manifest("ok"))
    import autopsy.worker.jobs as jobs
    real_diagnose = jobs.diagnose

    def fail_one(spans, artifacts, manifest, items=None):
        if manifest["pipeline"] == "boom":
            raise RuntimeError("worker test failure")
        return real_diagnose(spans, artifacts, manifest, items)

    monkeypatch.setattr(jobs, "diagnose", fail_one)
    assert _process_due() == 2
    with SessionLocal() as db:
        assert db.get(DiagnosisJobRecord, first).status == "failed"
        assert "Traceback" in db.get(DiagnosisJobRecord, first).error
        assert db.get(DiagnosisJobRecord, second).status == "done"


def test_rediagnosis_replaces_prior_observations_and_findings(client):
    execution_id = f"replace-{uuid.uuid4().hex[:8]}"
    _seed_simple(execution_id)
    with SessionLocal() as db:
        db.add(ObservationRecord(execution_id=execution_id, id="old", family="test", code="stale",
                                 result="fail", detail="stale"))
        db.add(FindingRecord(id="old-finding", execution_id=execution_id, role="origin", stage="stale"))
        db.commit()
    assert _process_due() == 1
    with SessionLocal() as db:
        assert db.query(ObservationRecord).filter_by(execution_id=execution_id, code="stale").count() == 0
        assert db.query(FindingRecord).filter_by(execution_id=execution_id, stage="stale").count() == 0
