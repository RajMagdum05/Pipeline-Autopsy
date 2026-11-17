from typing import Any, Dict, List
from sqlalchemy.orm import Session

from autopsy.adapters.otlp_adapter import OTLPAdapter
from autopsy.db.models import (
    PipelineModel,
    ExecutionModel,
    TraceModel,
    SpanModel,
    EventModel,
)


class TelemetryIngestionService:
    """
    Production-grade Telemetry Ingestion Service.

    Orchestrates parsing of OTLP/HTTP payloads via OTLPAdapter and performs
    idempotent persistence into PostgreSQL database tables.
    """

    def __init__(self):
        self.adapter = OTLPAdapter()

    def ingest_otlp_payload(self, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
        """
        Parses OTLP ExportTraceServiceRequest payload and persists normalized records into DB.

        Args:
            payload: Raw OTLP JSON payload.
            db: Active SQLAlchemy Session.

        Returns:
            Dict containing ingestion statistics (pipelines, executions, traces, spans, events persisted).
        """
        normalized_traces = self.adapter.parse_trace_request(payload)

        total_spans = 0
        total_events = 0
        persisted_traces = []

        for trace_item in normalized_traces:
            project_id = trace_item.get("project_id", "default")
            service_name = trace_item["service_name"]
            execution_id = trace_item["execution_id"]
            trace_id = trace_item["trace_id"]

            # 1. Pipeline Idempotent Upsert (by service name and project_id)
            pipeline = (
                db.query(PipelineModel)
                .filter(PipelineModel.name == service_name, PipelineModel.project_id == project_id)
                .first()
            )
            if not pipeline:
                pipeline = PipelineModel(
                    project_id=project_id,
                    name=service_name,
                    description=f"Auto-registered OTLP pipeline for service '{service_name}'",
                    tags=["otlp", "autopsy"],
                    metadata_json=trace_item["resource_attributes"],
                )
                db.add(pipeline)
                db.flush()

            # 2. Execution Idempotent Upsert (by execution_id)
            execution = (
                db.query(ExecutionModel)
                .filter(ExecutionModel.id == execution_id)
                .first()
            )
            if not execution:
                execution = ExecutionModel(
                    id=execution_id,
                    project_id=project_id,
                    pipeline_id=pipeline.id,
                    status="RUNNING",
                    started_at=trace_item["start_time"],
                    ended_at=trace_item["end_time"],
                    duration_ms=trace_item["duration_ms"],
                    environment=trace_item["resource_attributes"].get("environment", "production"),
                    trigger_type="otlp_ingestion",
                    attributes=trace_item["resource_attributes"],
                )
                db.add(execution)
                db.flush()

            # 3. Trace Idempotent Upsert (by trace_id)
            trace_rec = (
                db.query(TraceModel)
                .filter(TraceModel.trace_id == trace_id)
                .first()
            )
            if not trace_rec:
                trace_rec = TraceModel(
                    trace_id=trace_id,
                    execution_id=execution.id,
                    root_span_id=trace_item["root_span_id"],
                    start_time=trace_item["start_time"],
                    end_time=trace_item["end_time"],
                    duration_ms=trace_item["duration_ms"],
                    attributes=trace_item["resource_attributes"],
                )
                db.add(trace_rec)
                db.flush()
            else:
                # Update bounds and execution association if trace record exists
                trace_rec.execution_id = execution.id
                if trace_item["end_time"]:
                    trace_rec.end_time = trace_item["end_time"]
                if trace_item["duration_ms"]:
                    trace_rec.duration_ms = trace_item["duration_ms"]

            # 4. Spans & Events Idempotent Ingestion
            for span_data in trace_item["spans"]:
                span_id_hex = span_data["span_id"]

                span_rec = (
                    db.query(SpanModel)
                    .filter(
                        SpanModel.trace_id == trace_id,
                        SpanModel.span_id == span_id_hex,
                    )
                    .first()
                )

                if not span_rec:
                    span_rec = SpanModel(
                        span_id=span_id_hex,
                        trace_id=trace_id,
                        parent_span_id=span_data["parent_span_id"],
                        service_name=span_data["service_name"],
                        operation_name=span_data["operation_name"],
                        kind=span_data["kind"],
                        start_time=span_data["start_time"],
                        end_time=span_data["end_time"],
                        duration_ms=span_data["duration_ms"],
                        status_code=span_data["status_code"],
                        status_message=span_data["status_message"],
                        attributes=span_data["attributes"],
                    )
                    db.add(span_rec)
                    db.flush()
                    total_spans += 1
                else:
                    # Idempotent update
                    span_rec.status_code = span_data["status_code"]
                    span_rec.status_message = span_data["status_message"]
                    span_rec.attributes.update(span_data["attributes"])

                # Insert events
                for ev_data in span_data["events"]:
                    event_rec = EventModel(
                        span_db_id=span_rec.id,
                        span_id=span_id_hex,
                        timestamp=ev_data["timestamp"],
                        name=ev_data["name"],
                        attributes=ev_data["attributes"],
                    )
                    db.add(event_rec)
                    total_events += 1

            persisted_traces.append(trace_id)

        db.commit()

        return {
            "status": "success",
            "traces_processed": len(normalized_traces),
            "spans_persisted": total_spans,
            "events_persisted": total_events,
            "trace_ids": persisted_traces,
        }
