import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from autopsy.db.database import SessionLocal
from autopsy.db.models import (
    ArtifactRecord, DiagnosisJobRecord, ExecutionRecord, ExplanationRecord,
    FindingRecord, ObservationRecord, PipelineRecord, SpanRecord,
)
from autopsy.main import app


HEADERS = {"X-Autopsy-Api-Key": "autopsy-test-static-key"}


@pytest.fixture
def client():
    with TestClient(app, headers=HEADERS) as test_client:
        yield test_client


def _seed_execution(*, diagnosed=False, with_graph=False, pipeline_name=None):
    suffix = uuid.uuid4().hex[:8]
    name, execution_id = pipeline_name or f"read_{suffix}", f"read-exec-{suffix}"
    trace_id = uuid.uuid4().hex
    manifest = {
        "manifest": "pipeline-manifest/1", "pipeline": name, "version": "1.0.0",
        "external_inputs": ["source"], "items": {"roles": ["policy", "proof"]},
        "stages": [
            {"name": "validate", "scope": "item", "consumes": ["source"], "produces": ["checked"]},
            {"name": "fetch", "scope": "item", "requires": [{"stage": "validate", "item_role": "policy"}],
             "consumes": ["source"], "produces": ["page"]},
            {"name": "finalize", "scope": "run", "consumes": ["page"], "produces": ["result"]},
        ],
    }
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if db.get(PipelineRecord, ("default", name, "1.0.0")) is None:
            db.add(PipelineRecord(project_id="default", name=name, version="1.0.0", manifest=manifest,
                                  evidence_level="E1", evidence_kinds_allowed=[]))
        db.add(ExecutionRecord(id=execution_id, project_id="default", pipeline=name, version="1.0.0",
                               entity_id="entity-1", trace_ids=[trace_id], status="diagnosed" if diagnosed else "queued",
                               verdict="ROOT_CAUSE_IDENTIFIED" if diagnosed else None,
                               trace_grade="A" if diagnosed else None,
                               started_at=now - timedelta(minutes=1), diagnosed_at=now if diagnosed else None))
        root_attrs = {"pipeline.name": name, "pipeline.version": "1.0.0", "pipeline.run.id": execution_id,
                      "pipeline.span.role": "execution",
                      "pipeline.run.items": ["pol:policy", "proof:proof"] if with_graph else []}
        db.add(SpanRecord(trace_id=trace_id, span_id="root", execution_id=execution_id,
                          parent_span_id=None, name="run", kind="INTERNAL", role="execution", status="OK",
                          start_time=now, end_time=now, attrs=root_attrs, events=[], links=[], resource={}))
        if with_graph:
            stages = [
                ("validate", "pol", "policy", [], ["checked-pol"]),
                ("fetch", "proof", "proof", [], ["page-proof"]),
                ("finalize", None, None, ["page-proof"], ["result-run"]),
            ]
            for index, (stage, item, item_role, inputs, outputs) in enumerate(stages, 1):
                attrs = {"pipeline.name": name, "pipeline.version": "1.0.0", "pipeline.run.id": execution_id,
                         "pipeline.span.role": "stage", "pipeline.stage.name": stage,
                         "pipeline.stage.status": "success", "pipeline.stage.attempt": 1,
                         "pipeline.artifact.input_ids": inputs, "pipeline.artifact.output_ids": outputs}
                if item:
                    attrs.update({"pipeline.stage.item_id": item, "pipeline.stage.item_role": item_role})
                db.add(SpanRecord(trace_id=trace_id, span_id=f"stage-{index}", execution_id=execution_id,
                                  parent_span_id="root", name=stage, kind="INTERNAL", role="stage",
                                  stage_name=stage, item_id=item, attempt=1, status="OK", start_time=now,
                                  end_time=now, attrs=attrs, events=[], links=[], resource={}))
        if diagnosed:
            db.add(ObservationRecord(execution_id=execution_id, id="obs_001", family="check", code="quality.low",
                                     result="warn", stage="fetch@proof", detail="quality below target"))
            db.add(FindingRecord(id=f"finding-{suffix}", execution_id=execution_id, stage="fetch", item_id="proof",
                                 role="origin", classification="OUTPUT_CONTRACT_VIOLATION", confidence="supported",
                                 severity="warn", evidence=["obs_001"]))
            db.add(ExplanationRecord(execution_id=execution_id, source="template", summary="A stage failed.",
                                     narrative=[], remediation=[]))
        db.commit()
    return execution_id, name


def test_list_filters_and_cursor_pagination(client):
    first, pipeline = _seed_execution()
    second, _ = _seed_execution(pipeline_name=pipeline)
    response = client.get(f"/v1/executions?pipeline={pipeline}&limit=1", headers=HEADERS)
    assert response.status_code == 200
    assert len(response.json()["executions"]) == 1
    assert response.json()["executions"][0]["pipeline"] == pipeline
    assert response.json()["next_cursor"]
    page = client.get(f"/v1/executions?pipeline={pipeline}&limit=1&cursor={response.json()['next_cursor']}",
                      headers=HEADERS)
    assert page.status_code == 200
    assert len(page.json()["executions"]) == 1
    assert page.json()["executions"][0]["id"] != response.json()["executions"][0]["id"]
    assert page.json()["next_cursor"] is None


def test_execution_details_and_not_found(client, monkeypatch):
    execution_id, _ = _seed_execution()
    monkeypatch.setenv("JAEGER_BASE_URL", "http://jaeger.local")
    response = client.get(f"/v1/executions/{execution_id}", headers=HEADERS)
    assert response.status_code == 200
    assert len(response.json()["trace_ids"]) == 1
    assert response.json()["jaeger_url"].startswith("http://jaeger.local/trace/")
    assert client.get("/v1/executions/missing", headers=HEADERS).status_code == 404


def test_graph_contains_data_and_control_edges(client):
    execution_id, _ = _seed_execution(with_graph=True)
    response = client.get(f"/v1/executions/{execution_id}/graph", headers=HEADERS)
    assert response.status_code == 200
    graph = response.json()
    assert {node["id"] for node in graph["nodes"]} >= {"validate@pol", "fetch@proof", "finalize"}
    assert {edge["type"] for edge in graph["edges"]} == {"data", "control"}
    control = next(edge for edge in graph["edges"] if edge["type"] == "control")
    assert control["from"] == "validate@pol" and control["to"] == "fetch@proof"


def test_diagnosis_is_409_until_ready_then_returns_persisted_result(client):
    pending, _ = _seed_execution()
    response = client.get(f"/v1/executions/{pending}/diagnosis", headers=HEADERS)
    assert response.status_code == 409 and response.json() == {"status": "queued"}

    diagnosed, _ = _seed_execution(diagnosed=True)
    result = client.get(f"/v1/executions/{diagnosed}/diagnosis", headers=HEADERS)
    assert result.status_code == 200
    assert result.json()["verdict"] == "ROOT_CAUSE_IDENTIFIED"
    assert result.json()["findings"][0]["item_id"] == "proof"
    assert result.json()["observations"][0]["code"] == "quality.low"
    assert result.json()["explanation"]["source"] == "template"


def _set_signature(execution_id, signature):
    with SessionLocal() as db:
        finding = db.query(FindingRecord).filter_by(execution_id=execution_id).one()
        finding.signature = signature
        db.commit()
        return finding.id


def test_confirmed_finding_is_seen_on_replay(client):
    first, pipeline = _seed_execution(diagnosed=True, pipeline_name="feedback-replay")
    second, _ = _seed_execution(diagnosed=True, pipeline_name=pipeline)
    first_finding = _set_signature(first, "sig-feedback-confirmed")
    _set_signature(second, "sig-feedback-confirmed")

    feedback = client.post(f"/v1/findings/{first_finding}/feedback",
                           headers=HEADERS, json={"verdict": "confirmed", "comment": "verified"})
    assert feedback.status_code == 201
    replay = client.get(f"/v1/executions/{second}/diagnosis", headers=HEADERS)
    finding = replay.json()["findings"][0]
    assert finding["seen_before"] == 1
    assert finding["seen_before_last_at"]


def test_rejected_feedback_does_not_count_as_seen_before(client):
    first, pipeline = _seed_execution(diagnosed=True, pipeline_name="feedback-rejected")
    second, _ = _seed_execution(diagnosed=True, pipeline_name=pipeline)
    first_finding = _set_signature(first, "sig-feedback-rejected")
    _set_signature(second, "sig-feedback-rejected")

    feedback = client.post(f"/v1/findings/{first_finding}/feedback",
                           headers=HEADERS, json={"verdict": "rejected"})
    assert feedback.status_code == 201
    replay = client.get(f"/v1/executions/{second}/diagnosis", headers=HEADERS)
    assert replay.json()["findings"][0]["seen_before"] == 0


def test_normalized_spans_and_manual_requeue(client):
    execution_id, _ = _seed_execution()
    spans = client.get(f"/v1/executions/{execution_id}/spans", headers=HEADERS)
    assert spans.status_code == 200
    assert spans.json()["spans"][0]["attrs"]["autopsy.role"] == "execution"
    queued = client.post(f"/v1/executions/{execution_id}/diagnose", headers=HEADERS)
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    with SessionLocal() as db:
        assert db.get(DiagnosisJobRecord, execution_id).reason == "manual"
    assert client.get("/v1/executions/missing/spans", headers=HEADERS).status_code == 404


def test_delete_removes_rows_and_artifact_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_BLOB_DIR", str(tmp_path / "blobs"))
    execution_id, _ = _seed_execution()
    blob_dir = tmp_path / "blobs" / execution_id
    blob_dir.mkdir(parents=True)
    artifact_id = f"art_{uuid.uuid4().hex[:16]}"
    blob = blob_dir / artifact_id
    blob.write_text("payload", encoding="utf-8")
    with SessionLocal() as db:
        db.add(ArtifactRecord(id=artifact_id, execution_id=execution_id, kind="page", content_type="text/plain",
                              size_bytes=7, sha256="a" * 64, blob_path=str(blob), redacted=True))
        db.commit()
    response = client.delete(f"/v1/executions/{execution_id}", headers=HEADERS)
    assert response.status_code == 204
    assert not blob.exists()
    assert client.get(f"/v1/executions/{execution_id}", headers=HEADERS).status_code == 404


def test_health_contract_and_authentication(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert {"db", "worker", "queue_depth"} <= response.json().keys()
    unauthenticated = TestClient(app)
    try:
        assert unauthenticated.get("/v1/executions").status_code == 401
    finally:
        unauthenticated.close()
