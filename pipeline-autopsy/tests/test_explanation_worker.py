"""E5.3 worker integration: explanation mode never changes the deterministic diagnosis."""
import json
import uuid
from datetime import datetime, timedelta, timezone

from autopsy.db.database import SessionLocal
from autopsy.db.models import (
    DiagnosisJobRecord, ExecutionRecord, ExplanationRecord, FindingRecord, ObservationRecord,
)
from autopsy.explain.llm import DraftResponse
from autopsy.worker.jobs import process_due_jobs
import test_diagnosis_worker as worker_helpers
from test_diagnosis_worker import _seed_simple, client  # noqa: F401  (fixture)


def _seed_fanout(execution_id, tmp_path, monkeypatch):
    """Seed the shared fan-out fixture under a unique pipeline name."""
    manifest = dict(worker_helpers.FANOUT_MANIFEST, pipeline=f"explain-fanout-{uuid.uuid4().hex[:8]}")
    monkeypatch.setattr(worker_helpers, "FANOUT_MANIFEST", manifest)
    worker_helpers._seed_fanout(execution_id, tmp_path)


def _draft_from(bundle):
    """A guardrail-clean draft written only from the bundle the worker sends."""
    claim = {"origin": "origin", "propagated": "propagation", "tainted": "propagation",
             "not_executed": "impact"}
    narrative = []
    for finding in bundle["findings"]:
        ids = [row["id"] for row in finding["observations"]]
        if ids:
            narrative.append({"about": finding["stage"], "claim_type": claim.get(finding["role"], "context"),
                              "text": f"{finding['stage']} has evidence {ids[0]}.", "evidence_ids": ids[:1]})
    origin = next(f["stage"] for f in bundle["findings"] if f["role"] == "origin")
    return {"summary": f"{origin} is the origin.", "narrative": narrative, "remediation": []}


class GoodClient:
    model = "fake-good"

    def __init__(self):
        self.calls = 0

    def draft(self, bundle, violations=()):
        self.calls += 1
        return DraftResponse(json.dumps(_draft_from(bundle)), self.model, 10, 5)


class BadClient(GoodClient):
    model = "fake-bad"

    def draft(self, bundle, violations=()):
        self.calls += 1
        draft = _draft_from(bundle)
        draft["remediation"] = [{"text": "Reboot.", "playbook_id": "pb_does_not_exist"}]
        return DraftResponse(json.dumps(draft), self.model, 10, 5)


class TimeoutClient(GoodClient):
    def draft(self, bundle, violations=()):
        self.calls += 1
        raise TimeoutError()


def _run(execution_id, client_or_none):
    with SessionLocal() as db:
        job = db.get(DiagnosisJobRecord, execution_id)
        job.status, job.attempt = "pending", 0
        job.run_after = datetime.now(timezone.utc)
        db.commit()
    process_due_jobs(SessionLocal, now=datetime.now(timezone.utc) + timedelta(minutes=3),
                     llm_client_factory=lambda: client_or_none)


def _deterministic_snapshot(execution_id):
    with SessionLocal() as db:
        execution = db.get(ExecutionRecord, execution_id)
        findings = sorted(
            ({c.name: getattr(row, c.name) for c in FindingRecord.__table__.columns if c.name != "id"}
             for row in db.query(FindingRecord).filter_by(execution_id=execution_id)),
            key=lambda row: json.dumps(row, sort_keys=True, default=str))
        observations = sorted(
            ({c.name: getattr(row, c.name) for c in ObservationRecord.__table__.columns}
             for row in db.query(ObservationRecord).filter_by(execution_id=execution_id)),
            key=lambda row: row["id"])
        explanation = db.get(ExplanationRecord, execution_id)
        snapshot = json.dumps({"verdict": execution.verdict, "trace_grade": execution.trace_grade,
                               "status": execution.status, "findings": findings,
                               "observations": observations}, sort_keys=True, default=str).encode()
        return snapshot, explanation.source, explanation.model, explanation.guardrail_log


def test_diagnosis_bytes_identical_across_explanation_modes(client, tmp_path, monkeypatch):
    execution_id = f"explain-{uuid.uuid4().hex[:8]}"
    _seed_fanout(execution_id, tmp_path, monkeypatch)
    good, bad, slow = GoodClient(), BadClient(), TimeoutClient()

    _run(execution_id, None)
    template_bytes, source, model, log = _deterministic_snapshot(execution_id)
    assert (source, model, log) == ("template", None, [{"event": "skipped", "reason": "llm_not_configured"}])

    _run(execution_id, good)
    llm_bytes, source, model, log = _deterministic_snapshot(execution_id)
    assert (source, model, good.calls) == ("llm", "fake-good", 1)

    _run(execution_id, bad)
    fallback_bytes, source, model, log = _deterministic_snapshot(execution_id)
    assert (source, model, bad.calls) == ("template", "fake-bad", 2)
    assert {v["code"] for entry in log if "violations" in entry for v in entry["violations"]} == {"G7"}

    _run(execution_id, slow)
    timeout_bytes, source, _, log = _deterministic_snapshot(execution_id)
    assert (source, slow.calls, log[0]["error"]) == ("template", 1, "TimeoutError")

    assert template_bytes == llm_bytes == fallback_bytes == timeout_bytes
    response = client.get(f"/v1/executions/{execution_id}/diagnosis")
    assert response.json()["explanation"]["source"] == "template"


def test_llm_explanation_is_served_by_api(client, tmp_path, monkeypatch):
    execution_id = f"explain-api-{uuid.uuid4().hex[:8]}"
    _seed_fanout(execution_id, tmp_path, monkeypatch)
    _run(execution_id, GoodClient())
    with SessionLocal() as db:
        row = db.get(ExplanationRecord, execution_id)
        assert (row.source, row.tokens_in, row.tokens_out) == ("llm", 10, 5)
        assert row.latency_ms is not None
    body = client.get(f"/v1/executions/{execution_id}/diagnosis").json()["explanation"]
    assert body["source"] == "llm"
    assert all(isinstance(line, str) for line in body["narrative"])


def test_healthy_run_never_calls_llm(client):
    execution_id = f"explain-healthy-{uuid.uuid4().hex[:8]}"
    _seed_simple(execution_id)
    spy = GoodClient()
    _run(execution_id, spy)
    assert spy.calls == 0
    with SessionLocal() as db:
        row = db.get(ExplanationRecord, execution_id)
        assert row.source == "template"
        assert row.guardrail_log == [{"event": "skipped", "reason": "no_findings"}]


def test_broken_llm_factory_never_fails_diagnosis(client):
    execution_id = f"explain-factory-{uuid.uuid4().hex[:8]}"
    _seed_simple(execution_id)

    def broken():
        raise RuntimeError("bad config")

    with SessionLocal() as db:
        db.get(DiagnosisJobRecord, execution_id).run_after = datetime.now(timezone.utc)
        db.commit()
    process_due_jobs(SessionLocal, now=datetime.now(timezone.utc) + timedelta(minutes=3),
                     llm_client_factory=broken)
    with SessionLocal() as db:
        assert db.get(DiagnosisJobRecord, execution_id).status == "done"
