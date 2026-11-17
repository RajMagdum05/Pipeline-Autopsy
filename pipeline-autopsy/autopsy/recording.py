"""Opt-in, local recording of ingest inputs for deterministic L1 replay."""
import json
import logging
import os
import re
from pathlib import Path

import yaml

from autopsy.db.models import ExecutionRecord, PipelineRecord, SpanRecord


logger = logging.getLogger(__name__)
_SAFE_CASE = re.compile(r"[^A-Za-z0-9._-]+")
_DRAFT_EXPECTED = """# Draft created by AUTOPSY_RECORD_DIR. Review before using this case in L1.\nverdict: TODO\ntrace_grade: TODO\norigins: []\nfindings: {}\nrequired_evidence_codes: []\n"""


def _case_dir(execution_id):
    record_dir = os.getenv("AUTOPSY_RECORD_DIR")
    if not record_dir:
        return None
    safe_id = _SAFE_CASE.sub("_", str(execution_id)).strip("._")
    if not safe_id:
        return None
    return Path(record_dir).expanduser() / safe_id


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def record_ingest(db, request_payload, trace_ids):
    """Record each accepted execution's OTLP JSON and registered manifest."""
    if not os.getenv("AUTOPSY_RECORD_DIR"):
        return
    try:
        spans = db.query(SpanRecord).filter(SpanRecord.trace_id.in_(trace_ids)).all() if trace_ids else []
        execution_ids = sorted({span.execution_id for span in spans if span.execution_id})
        for execution_id in execution_ids:
            case_dir = _case_dir(execution_id)
            if case_dir is None:
                continue
            execution = db.get(ExecutionRecord, execution_id)
            pipeline = (db.get(PipelineRecord, (execution.project_id, execution.pipeline, execution.version))
                        if execution else None)
            _write_json(case_dir / "trace.json", request_payload)
            (case_dir / "artifacts").mkdir(parents=True, exist_ok=True)
            if pipeline and pipeline.manifest:
                (case_dir / "manifest.yaml").write_text(
                    yaml.safe_dump(pipeline.manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
            expected = case_dir / "expected.yaml"
            if not expected.exists():
                expected.write_text(_DRAFT_EXPECTED, encoding="utf-8")
    except Exception as exc:
        logger.warning("Autopsy recording failed (%s); ingestion remains successful", type(exc).__name__)


def record_artifact(payload):
    """Record the accepted artifact upload payload alongside its trace."""
    if not os.getenv("AUTOPSY_RECORD_DIR") or not isinstance(payload, dict):
        return
    case_dir = _case_dir(payload.get("execution_id", ""))
    artifact_id = payload.get("id")
    if case_dir is None or not isinstance(artifact_id, str) or not re.fullmatch(r"art_[0-9a-f]{16}", artifact_id):
        return
    try:
        _write_json(case_dir / "artifacts" / f"{artifact_id}.json", payload)
    except Exception as exc:
        logger.warning("Autopsy artifact recording failed (%s); upload remains successful", type(exc).__name__)
