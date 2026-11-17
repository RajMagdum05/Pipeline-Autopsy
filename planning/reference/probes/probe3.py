import os,sys,json
os.environ["AUTOPSY_DATABASE_URL"]="sqlite:////tmp/probe3.db"
if os.path.exists("/tmp/probe3.db"): os.remove("/tmp/probe3.db")
sys.path.insert(0,"/home/claude/local/pipeline-autopsy")
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
exp=InMemorySpanExporter(); tp=TracerProvider(); tp.add_span_processor(SimpleSpanProcessor(exp)); t=tp.get_tracer("x")
with t.start_as_current_span("execution") as root:
    root.set_attributes({"autopsy.role":"execution","execution.id":"exec_1"})
    with t.start_as_current_span("information_extraction") as s:
        s.set_attributes({"autopsy.role":"stage","stage.attempt":2,"input.artifact_ids":["art_a","art_b"],"output.artifact_ids":[]})
        s.add_event("autopsy.check",{"check.id":"extraction.schema","check.result":"fail","check.observed":0.61})
from fastapi.testclient import TestClient
from autopsy.main import app
from autopsy.db.database import SessionLocal
from autopsy.db import models
with TestClient(app) as c:
    r=c.post("/v1/traces",content=encode_spans(exp.get_finished_spans()).SerializeToString(),headers={"content-type":"application/x-protobuf"})
    print(r.status_code, r.json())
db=SessionLocal()
for sp in db.query(models.SpanModel).all():
    print(sp.operation_name, json.dumps(sp.attributes, default=str))
for ev in db.query(models.EventModel).all():
    print("EVENT", {k:getattr(ev,k) for k in ev.__table__.columns.keys()})
print([n for n in dir(models) if n.endswith("Model")])
for sp in db.query(models.SpanModel).all():
    print("SPAN", sp.operation_name, sp.span_id, sp.parent_span_id, sp.trace_id)
