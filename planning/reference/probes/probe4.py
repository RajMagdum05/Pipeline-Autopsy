import os,sys
os.environ["AUTOPSY_DATABASE_URL"]="sqlite:////tmp/probe4.db"
if os.path.exists("/tmp/probe4.db"): os.remove("/tmp/probe4.db")
sys.path.insert(0,"/home/claude/local/pipeline-autopsy")
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
exp=InMemorySpanExporter(); tp=TracerProvider(); tp.add_span_processor(SimpleSpanProcessor(exp)); t=tp.get_tracer("x")
with t.start_as_current_span("a"):
    with t.start_as_current_span("b"): pass
body=encode_spans(exp.get_finished_spans()).SerializeToString()
from fastapi.testclient import TestClient
from autopsy.main import app
from autopsy.db.database import SessionLocal
from autopsy.db import models
with TestClient(app) as c:
    for i in range(2):
        r=c.post("/v1/traces",content=body,headers={"content-type":"application/x-protobuf"}); print(i, r.status_code, str(r.json())[:160])
    r=c.post("/v1/traces",content=b'{"resourceSpans":[{"scopeSpans":[{"spans":[{"traceId":"zz","spanId":"1"}]}]}]}',headers={"content-type":"application/json"}); print("malformed", r.status_code, str(r.json())[:200])
db=SessionLocal(); print("span rows:", db.query(models.SpanModel).count())
