from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from autopsy.db.database import Base
from autopsy.explain.bundle import build_bundle
from autopsy.knowledge.playbooks import load_playbooks, retrieve
from types import SimpleNamespace


def _db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'playbooks.db'}")
    Base.metadata.create_all(engine)
    return engine


def test_loads_eight_starter_playbooks():
    playbooks = load_playbooks()
    assert len(playbooks) == 8
    assert len({row['id'] for row in playbooks}) == 8


def test_insurance_ocr_finding_selects_keyed_playbook(tmp_path):
    engine = _db(tmp_path)
    observation = SimpleNamespace(id="obs_001", code="ocr.quality", result="warn",
                                  stage="document_processing@bill", artifact_id="art_bill",
                                  field="bill_date", detail="low confidence")
    result = {"verdict": "ROOT_CAUSE_FOUND", "trace_grade": "A",
              "findings": [{"stage": "document_processing@bill", "role": "origin",
                            "classification": "OUTPUT_CONTRACT_VIOLATION", "confidence": "supported",
                            "severity": "warn", "evidence": ["obs_001"]}],
              "observations": [observation]}
    bundle = build_bundle(result, {}, evidence_level="E1")
    with Session(engine) as db:
        found = retrieve(db, bundle["findings"])
    assert found[0]["playbook_id"] == "pb_ocr_low_quality"


def test_timeout_error_selects_upstream_playbook(tmp_path):
    engine = _db(tmp_path)
    findings = [{"stage": "publish", "role": "origin", "classification": "SERVICE_EXECUTION_FAILURE",
                 "observations": []}]
    spans = [{"stage_name": "publish", "error_type": "TimeoutError"}]
    with Session(engine) as db:
        found = retrieve(db, findings, spans)
    assert found[0]["playbook_id"] == "pb_upstream_timeout"


def test_unknown_pattern_returns_no_playbook(tmp_path):
    engine = _db(tmp_path)
    findings = [{"stage": "mystery", "role": "origin", "classification": "UNRECOGNIZED_SIGNAL",
                 "observations": []}]
    with Session(engine) as db:
        assert retrieve(db, findings) == []


def test_text_fallback_finds_matching_playbook(tmp_path):
    engine = _db(tmp_path)
    findings = [{"stage": "queue", "role": "origin", "classification": "TIMEOUT_FROM_QUEUE",
                 "observations": []}]
    with Session(engine) as db:
        found = retrieve(db, findings)
    assert found[0]["playbook_id"] == "pb_upstream_timeout"
