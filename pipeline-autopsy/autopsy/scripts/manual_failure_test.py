import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from autopsy.db import SessionLocal, FailureModel, EvidenceModel, ExecutionModel
from autopsy.db.init_db import init_autopsy_db
from autopsy.services.failure_detection_service import FailureDetectionService


def run_manual_failure_test():
    print("=" * 70)
    print("STEP 5 MANUAL TEST: OpenTelemetry Failure Producer -> Autopsy -> PostgreSQL Failures & Evidence")
    print("=" * 70)

    # 1. Initialize Database
    init_autopsy_db()

    # 2. Setup OpenTelemetry SDK Tracer
    resource = Resource.create({
        "service.name": "manual_failure_pipeline",
        "execution.id": "exec-failure-manual-2026",
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint="http://127.0.0.1:8080/v1/traces", timeout=5)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("manual_failure_tracer")

    print("[1/4] Instrumenting synthetic pipeline with intentional failure...")

    with tracer.start_as_current_span("stage_0_orchestrator") as s0:
        time.sleep(0.01)

        # Stage 1: Data Ingest (Success)
        with tracer.start_as_current_span("stage_1_data_ingest") as s1:
            s1.set_attribute("records.count", 100)
            time.sleep(0.01)

        # Stage 2: Database Writer (Failure with Status=ERROR & Exception Event)
        with tracer.start_as_current_span("stage_2_db_writer") as s2:
            s2.set_attribute("db.instance", "prod-primary")
            s2.set_status(trace.Status(trace.StatusCode.ERROR, "Database transaction deadlock"))
            s2.add_event(
                "exception",
                attributes={
                    "exception.type": "TransactionDeadlockError",
                    "exception.message": "Deadlock detected during row lock on table 'transactions'",
                },
            )
            time.sleep(0.01)

    trace_id_hex = f"{s0.get_span_context().trace_id:032x}"
    s2_span_id_hex = f"{s2.get_span_context().span_id:016x}"

    print(f"[2/4] Failure Trace generated: trace_id={trace_id_hex}")
    print("[3/4] Exporting OTLP telemetry to Autopsy...")
    provider.force_flush()

    print("[4/4] Executing FailureDetectionService against PostgreSQL database...")
    db = SessionLocal()
    try:
        failure_service = FailureDetectionService()
        result = failure_service.detect_and_persist_from_db(trace_id_hex, db)

        print("\n" + "=" * 70)
        print("FAILURE DETECTION SERVICE RESULTS:")
        print(f"Status: {result['status']} | Execution ID: '{result['execution_id']}'")
        print(f"Findings: {result['findings_count']} | Failures Persisted: {result['failures_persisted']} | Evidence Persisted: {result['evidence_persisted']}")
        print("=" * 70)

        # Query and display stored FailureModel and EvidenceModel records
        exec_rec = db.query(ExecutionModel).filter_by(id="exec-failure-manual-2026").first()
        print(f"\n---> EXECUTION RECORD: id={exec_rec.id}, status={exec_rec.status}")

        failures = db.query(FailureModel).filter_by(execution_id="exec-failure-manual-2026").all()
        print(f"\n---> PERSISTED FAILURES ({len(failures)}):")
        for f in failures:
            print(f"  * Failure ID: {f.id}")
            print(f"    - Type: {f.failure_type} | Severity: {f.severity} | Error Class: {f.error_class}")
            print(f"    - Span ID: {f.span_id}")
            print(f"    - Description: {f.description}")
            print(f"    - Linked Evidence IDs ({len(f.evidence_ids)}): {f.evidence_ids}")

        evidence_recs = db.query(EvidenceModel).filter_by(execution_id="exec-failure-manual-2026").all()
        print(f"\n---> PERSISTED EVIDENCE ({len(evidence_recs)}):")
        for ev in evidence_recs:
            print(f"  * Evidence ID: {ev.id}")
            print(f"    - Type: {ev.evidence_type}")
            print(f"    - Reference URI: {ev.reference_uri}")
            print(f"    - Summary: {ev.summary}")

    finally:
        db.close()

    print("\n" + "=" * 70)
    print("STEP 5 MANUAL FAILURE DETECTION VERIFICATION SUCCESSFUL!")
    print("=" * 70)


if __name__ == "__main__":
    run_manual_failure_test()
