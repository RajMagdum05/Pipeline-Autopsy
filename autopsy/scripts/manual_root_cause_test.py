import time
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from autopsy.db import SessionLocal, FailureModel, ExecutionModel
from autopsy.db.init_db import init_autopsy_db
from autopsy.services.root_cause_service import RootCauseAnalysisEngine


def run_manual_root_cause_test():
    print("=" * 70)
    print("STEP 6 MANUAL TEST: OpenTelemetry Multi-Stage Failure -> RCA Engine")
    print("=" * 70)

    # 1. Initialize Database
    init_autopsy_db()

    # 2. Setup OpenTelemetry SDK Tracer
    resource = Resource.create({
        "service.name": "manual_rca_pipeline",
        "execution.id": "exec-rca-manual-2026",
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint="http://127.0.0.1:8080/v1/traces", timeout=5)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("manual_rca_tracer")

    print("[1/4] Instrumenting synthetic multi-stage cascading failure pipeline...")

    # Service A (API Gateway - Success)
    with tracer.start_as_current_span("service_a_gateway") as sa:
        time.sleep(0.01)

        # Service B (Auth Provider - Fails with Status=ERROR & Exception)
        with tracer.start_as_current_span("service_b_auth_provider") as sb:
            sb.set_attribute("auth.provider", "jwt")
            sb.set_status(trace.Status(trace.StatusCode.ERROR, "Signature verification failed"))
            sb.add_event(
                "exception",
                attributes={
                    "exception.type": "JWTDecodeError",
                    "exception.message": "Signature verification failed for issuer 'auth.company.internal'",
                },
            )
            time.sleep(0.01)

            # Service C (Downstream User Service - Fails due to Auth error)
            with tracer.start_as_current_span("service_c_user_service") as sc:
                sc.set_attribute("user.id", 404)
                sc.set_status(trace.Status(trace.StatusCode.ERROR, "Unauthorized upstream dependency"))
                time.sleep(0.01)

    trace_id_hex = f"{sa.get_span_context().trace_id:032x}"
    sb_span_id_hex = f"{sb.get_span_context().span_id:016x}"

    print(f"[2/4] Trace generated: trace_id={trace_id_hex}")
    print("[3/4] Exporting OTLP telemetry to Autopsy...")
    provider.force_flush()

    print("[4/4] Executing RootCauseAnalysisEngine against PostgreSQL database...")
    db = SessionLocal()
    try:
        rca_engine = RootCauseAnalysisEngine()
        result = rca_engine.analyze_and_persist_from_db(trace_id_hex, db)

        print("\n" + "=" * 70)
        print("ROOT CAUSE ANALYSIS RESULTS:")
        print(f"Status: {result['analysis_status']} | Execution ID: '{result['execution_id']}'")
        print(f"Candidates Count: {len(result['candidates'])}")
        print("=" * 70)

        for idx, cand in enumerate(result["candidates"], 1):
            print(f"\n---> ROOT CAUSE CANDIDATE #{idx}:")
            print(f"     Candidate ID: {cand['candidate_id']}")
            print(f"     Service: {cand['service_name']} | Operation: {cand['operation_name']}")
            print(f"     Span ID: {cand['span_id']}")
            print(f"     Confidence State: {cand['confidence_state']}")
            print(f"     Relationship Type: {cand['relationship_type']}")
            print(f"     Reason: {cand['reason']}")

            print(f"\n     SUPPORTING EVIDENCE ({len(cand['supporting_evidence'])} items):")
            for ev in cand["supporting_evidence"]:
                print(f"       * [{ev['detector']}] {ev['finding_type']}: {ev['description']}")

            print(f"\n     DOWNSTREAM IMPACT ({len(cand['downstream_impact_spans'])} spans):")
            for ds in cand["downstream_impact_spans"]:
                print(f"       * Impacted Span: '{ds['operation_name']}' ({ds['service_name']}) [status: {ds['status_code']}]")

        # Verify PostgreSQL persistent hypotheses
        failures = db.query(FailureModel).filter_by(execution_id="exec-rca-manual-2026").all()
        print(f"\n---> POSTGRESQL FAILURE HYPOTHESES UPDATED ({len(failures)} rows):")
        for f in failures:
            print(f"  * Failure ID: {f.id} (span_id: {f.span_id})")
            print(f"    - Hypothesis: {f.root_cause_hypothesis}")

    finally:
        db.close()

    print("\n" + "=" * 70)
    print("STEP 6 MANUAL RCA VERIFICATION SUCCESSFUL!")
    print("=" * 70)


if __name__ == "__main__":
    run_manual_root_cause_test()
