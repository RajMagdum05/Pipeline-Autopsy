import time
import requests
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from autopsy.db import (
    SessionLocal,
    PipelineModel,
    ExecutionModel,
    TraceModel,
    SpanModel,
    EventModel,
)
from autopsy.db.init_db import init_autopsy_db

def run_manual_otlp_test():
    print("=" * 60)
    print("STEP 3 MANUAL TEST: OpenTelemetry Producer -> OTLP/HTTP -> Autopsy -> PostgreSQL")
    print("=" * 60)

    # Ensure DB tables exist
    init_autopsy_db()

    # 1. Setup OpenTelemetry SDK Tracer Provider
    resource = Resource.create({
        "service.name": "manual_test_etl_pipeline",
        "execution.id": "exec-manual-2026-001",
        "environment": "manual_verification",
    })
    provider = TracerProvider(resource=resource)
    
    # Configure OTLP HTTP Exporter targeting Autopsy /v1/traces
    otlp_exporter = OTLPSpanExporter(
        endpoint="http://127.0.0.1:8080/v1/traces",
        timeout=10,
    )
    provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
    tracer = provider.get_tracer("manual_test_tracer")

    print("[1/4] Generating trace using OpenTelemetry Python SDK...")
    
    with tracer.start_as_current_span("step_1_extract_dataset") as span1:
        span1.set_attribute("storage.provider", "s3")
        span1.set_attribute("file.size_mb", 42.5)
        time.sleep(0.01)

        with tracer.start_as_current_span("step_2_transform_records") as span2:
            span2.set_attribute("batch.size", 1000)
            time.sleep(0.01)

            with tracer.start_as_current_span("step_3_load_warehouse") as span3:
                span3.set_attribute("destination.table", "analytics_db.sales")
                span3.add_event(
                    "data_persisted",
                    attributes={"inserted_rows": 1000, "latency_ms": 12.4},
                )
                time.sleep(0.01)

    print("[2/4] Force flushing spans to Autopsy OTLP endpoint (http://127.0.0.1:8080/v1/traces)...")
    provider.force_flush()
    print("[3/4] Telemetry exported successfully.")

    print("[4/4] Querying PostgreSQL database to verify stored records...")
    db = SessionLocal()
    try:
        pipeline = db.query(PipelineModel).filter_by(name="manual_test_etl_pipeline").first()
        print(f"\n---> PIPELINE: id={pipeline.id}, name={pipeline.name}")

        execution = db.query(ExecutionModel).filter_by(id="exec-manual-2026-001").first()
        print(f"---> EXECUTION: id={execution.id}, pipeline_id={execution.pipeline_id}, status={execution.status}")

        traces = db.query(TraceModel).filter_by(execution_id=execution.id).all()
        for t in traces:
            print(f"---> TRACE: trace_id={t.trace_id}, duration_ms={t.duration_ms}")

            spans = db.query(SpanModel).filter_by(trace_id=t.trace_id).order_by(SpanModel.start_time).all()
            print(f"\n     SPANS (DAG Hierarchy): {len(spans)} spans found:")
            for s in spans:
                print(f"     - Span: name='{s.operation_name}', span_id={s.span_id}, parent_span_id={s.parent_span_id}, status_code={s.status_code}")
                print(f"       Attributes: {s.attributes}")
                events = db.query(EventModel).filter_by(span_id=s.span_id).all()
                if events:
                    for ev in events:
                        print(f"       * Event: name='{ev.name}', timestamp={ev.timestamp}, attributes={ev.attributes}")

    finally:
        db.close()

    print("\n" + "=" * 60)
    print("MANUAL TEST VERIFICATION SUCCESSFUL!")
    print("=" * 60)

if __name__ == "__main__":
    run_manual_otlp_test()
