"""Runtime probe: real OTel SDK spans -> protobuf -> existing Autopsy /v1/traces -> RCA + diagnose.

Scenarios (shaped like the old insurance pipeline: sibling stage spans under one root):
  A  rule_engine raises, exception propagates to root
  B  silent failure: stage.status=failed set as attribute, OTel status OK
  C  extraction produced bad value (only visible in attributes), rule_engine fails with data error
"""
import json
import os
import sys

os.environ["AUTOPSY_DATABASE_URL"] = "sqlite:////tmp/probe_autopsy.db"
if os.path.exists("/tmp/probe_autopsy.db"):
    os.remove("/tmp/probe_autopsy.db")
sys.path.insert(0, "/home/claude/local/pipeline-autopsy")

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.trace import Status, StatusCode

from fastapi.testclient import TestClient
from autopsy.main import app

exp = InMemorySpanExporter()
tp = TracerProvider(resource=Resource.create({"service.name": "insurance-pipeline"}))
tp.add_span_processor(SimpleSpanProcessor(exp))
tracer = tp.get_tracer("probe")

BASE = {"pipeline.name": "insurance-pipeline", "pipeline.version": "1.0.0"}


def stage(name, exec_id, status="success", raise_exc=None, extra=None):
    with tracer.start_as_current_span(name) as sp:
        sp.set_attributes({**BASE, "execution.id": exec_id, "execution.entity_id": "CLM-1",
                           "stage.name": name, "stage.status": status,
                           "input.artifact_ids": [], "output.artifact_ids": []})
        if extra:
            sp.set_attributes(extra)
        if raise_exc:
            sp.set_attribute("stage.status", "failed")
            raise raise_exc


def run(scenario, exec_id):
    exp.clear()
    try:
        with tracer.start_as_current_span("claim_processing") as root:
            root.set_attributes({**BASE, "execution.id": exec_id, "execution.entity_id": "CLM-1",
                                 "stage.name": "claim_processing", "stage.status": "running"})
            stage("document_processing", exec_id)
            if scenario == "C":
                stage("information_extraction", exec_id, extra={"validation.status": "FAILED",
                                                                "extracted.diagnosis_code": "XYZ"})
            else:
                stage("information_extraction", exec_id)
            if scenario in ("A", "C"):
                stage("rule_engine", exec_id, raise_exc=ValueError("No matching policy rule"))
            else:
                stage("rule_engine", exec_id, status="failed")  # silent failure
                stage("final_result", exec_id)
    except ValueError:
        pass
    spans = exp.get_finished_spans()
    body = encode_spans(spans).SerializeToString()
    return spans[0].context.trace_id, body


client = TestClient(app); client.__enter__()
out = {}
for sc in ("A", "B", "C"):
    tid_int, body = run(sc, f"exec-{sc}")
    tid = format(tid_int, "032x")
    r = client.post("/v1/traces", content=body, headers={"content-type": "application/x-protobuf"})
    ing = r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    rc = client.post(f"/v1/traces/{tid}/root-cause").json()
    dg = client.post(f"/v1/traces/{tid}/diagnose?use_llm=false").json()
    out[sc] = {
        "ingest_status": ing[0], "ingest_body": str(ing[1])[:300],
        "rca_status": rc.get("analysis_status"),
        "rca_candidates": [(c["operation_name"], c["relationship_type"], c["confidence_state"],
                            [d.get("operation_name") for d in c.get("downstream_impact_spans", [])])
                           for c in rc.get("candidates", [])],
        "diagnosis_keys": sorted(dg.keys())[:12] if isinstance(dg, dict) else str(dg)[:200],
        "diagnosis_root": (dg.get("root_cause") or dg.get("primary_root_cause") or dg.get("status")) if isinstance(dg, dict) else None,
    }
print(json.dumps(out, indent=2, default=str))
