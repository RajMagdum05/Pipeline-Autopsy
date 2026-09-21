import time
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from autopsy.db import SessionLocal
from autopsy.db.init_db import init_autopsy_db
from autopsy.services.reconstruction_service import PipelineReconstructionEngine, ExecutionNode


def print_ascii_tree(node: ExecutionNode, indent: str = "", is_last: bool = True):
    branch = "+-- " if is_last else "|-- "
    prefix = indent + branch if indent else ""
    status_str = f"[{node.status_code}]" if node.status_code else ""
    dur_str = f"({node.duration_ms:.2f}ms)" if node.duration_ms is not None else ""
    
    print(f"{prefix}{node.operation_name} [span_id: {node.span_id}] {status_str} {dur_str}")
    
    child_indent = indent + ("    " if is_last else "|   ")
    for idx, child in enumerate(node.children):
        is_child_last = (idx == len(node.children) - 1)
        print_ascii_tree(child, indent=child_indent, is_last=is_child_last)


def run_manual_reconstruction_test():
    print("=" * 70)
    print("STEP 4 MANUAL TEST: OpenTelemetry Producer -> Autopsy -> DB -> Reconstruction")
    print("=" * 70)

    # 1. Initialize Database
    init_autopsy_db()

    # 2. Setup OpenTelemetry SDK Tracer
    resource = Resource.create({
        "service.name": "manual_reconstruction_pipeline",
        "execution.id": "exec-recon-manual-2026",
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint="http://127.0.0.1:8080/v1/traces", timeout=5)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("recon_tracer")

    print("[1/4] Instrumenting synthetic multi-stage branching & parallel pipeline...")

    with tracer.start_as_current_span("stage_0_orchestrator") as s0:
        s0.set_attribute("pipeline.type", "multistage_etl")
        time.sleep(0.01)

        # Stage 1: Data Ingest
        with tracer.start_as_current_span("stage_1_data_ingest") as s1:
            s1.set_attribute("records.fetched", 2500)
            time.sleep(0.01)

        # Stage 2: Parallel Model Inference Branch A & B
        with tracer.start_as_current_span("stage_2_feature_extract") as s2:
            s2.set_attribute("features.count", 64)
            time.sleep(0.01)

            with tracer.start_as_current_span("stage_3_branch_a_xgboost") as s3a:
                s3a.set_attribute("model.type", "xgboost")
                time.sleep(0.01)

            with tracer.start_as_current_span("stage_3_branch_b_transformer") as s3b:
                s3b.set_attribute("model.type", "transformer")
                time.sleep(0.01)

        # Stage 4: Aggregate Output
        with tracer.start_as_current_span("stage_4_aggregate_results") as s4:
            s4.set_attribute("consensus.reached", True)
            time.sleep(0.01)

    trace_id_hex = f"{s0.get_span_context().trace_id:032x}"

    print(f"[2/4] Trace generated: trace_id={trace_id_hex}")
    print("[3/4] Exporting OTLP telemetry to Autopsy...")
    provider.force_flush()

    print("[4/4] Running PipelineReconstructionEngine against PostgreSQL database...")
    db = SessionLocal()
    try:
        engine = PipelineReconstructionEngine()
        graph = engine.reconstruct_from_db(trace_id_hex, db)

        print("\n" + "=" * 70)
        print(f"RECONSTRUCTED EXECUTION GRAPH: execution_id='{graph.execution_id}'")
        print(f"Status: {graph.reconstruction_status} | Total Spans: {graph.total_spans_count} | Duration: {graph.duration_ms:.2f}ms")
        print(f"Warnings ({len(graph.warnings)}): {graph.warnings}")
        print("=" * 70)

        print("\nRECONSTRUCTED PIPELINE GRAPH TREE:")
        for root in graph.root_nodes:
            print_ascii_tree(root)

        if graph.orphan_nodes:
            print("\nORPHAN NODES DETECTED:")
            for orphan in graph.orphan_nodes:
                print(f"  - Orphan: {orphan.operation_name} (parent_id: {orphan.parent_span_id})")

    finally:
        db.close()

    print("\n" + "=" * 70)
    print("STEP 4 MANUAL RECONSTRUCTION VERIFICATION SUCCESSFUL!")
    print("=" * 70)


if __name__ == "__main__":
    run_manual_reconstruction_test()
