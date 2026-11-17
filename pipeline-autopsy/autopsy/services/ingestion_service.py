from typing import Any, Dict, List
from sqlalchemy.orm import Session

from autopsy.ingest.otlp import OTLPAdapter
from autopsy.core.normalize import normalize
from autopsy.db.models import (
    ProjectRecord,
    PipelineRecord,
    ExecutionRecord,
    SpanRecord,
)
from autopsy.worker.jobs import schedule_diagnosis


class TelemetryIngestionService:
    """
    Production-grade Telemetry Ingestion Service.

    Orchestrates parsing of OTLP/HTTP payloads via OTLPAdapter and performs
    idempotent persistence into PostgreSQL database tables.
    """

    def __init__(self):
        self.adapter = OTLPAdapter()

    def _upsert_v2_records(self, trace_item: Dict[str, Any], db: Session) -> None:
        project_id = str(trace_item.get("project_id") or "default")
        trace_id = trace_item["trace_id"]
        resource_attrs = trace_item.get("resource_attributes", {})
        root_span = next((span for span in trace_item["spans"] if span.get("parent_span_id") is None),
                         trace_item["spans"][0])
        root_attrs = root_span.get("attributes", {})
        pipeline_name = str(root_attrs.get("pipeline.name") or resource_attrs.get("pipeline.name")
                            or trace_item["service_name"])
        pipeline_version = str(root_attrs.get("pipeline.version") or resource_attrs.get("pipeline.version")
                               or resource_attrs.get("service.version") or "0.0.0")
        entity_id = root_attrs.get("pipeline.entity.id") or root_attrs.get("execution.entity_id")

        project = db.query(ProjectRecord).filter_by(id=project_id).first()
        if project is None:
            project = ProjectRecord(id=project_id, name=project_id)
            db.add(project)
            db.flush()

        pipeline = db.query(PipelineRecord).filter_by(
            project_id=project_id, name=pipeline_name, version=pipeline_version
        ).first()
        if pipeline is None:
            pipeline = PipelineRecord(project_id=project_id, name=pipeline_name, version=pipeline_version,
                                      manifest={}, evidence_level="E1", evidence_kinds_allowed=[])
            db.add(pipeline)
            db.flush()

        execution_id = str(trace_item["execution_id"])
        execution = db.query(ExecutionRecord).filter_by(id=execution_id).first()
        if execution is None:
            previous_id = root_attrs.get("pipeline.run.previous_id")
            if previous_id and db.query(ExecutionRecord).filter_by(id=str(previous_id)).first() is None:
                previous_id = None
            execution = ExecutionRecord(
                id=execution_id,
                project_id=project_id,
                pipeline=pipeline_name,
                version=pipeline_version,
                entity_id=str(entity_id) if entity_id is not None else None,
                trace_ids=[],
                status="receiving",
                run_outcome=root_attrs.get("pipeline.run.outcome"),
                started_at=trace_item["start_time"],
                ended_at=trace_item.get("end_time") if root_attrs.get("pipeline.run.outcome") else None,
                previous_execution_id=str(previous_id) if previous_id else None,
            )
            db.add(execution)
            db.flush()
        elif entity_id is not None:
            execution.entity_id = str(entity_id)

        trace_ids = list(execution.trace_ids or [])
        if trace_id not in trace_ids:
            trace_ids.append(trace_id)
            execution.trace_ids = trace_ids

        for span_data in trace_item["spans"]:
            attrs = normalize([{
                "span_id": span_data["span_id"],
                "trace_id": trace_id,
                "attrs": span_data.get("attributes", {}),
                "resource": {"attributes": resource_attrs},
            }])[0]["attrs"]
            role = attrs.get("pipeline.span.role", attrs.get("autopsy.role", "other"))
            if role not in {"execution", "stage", "operation"}:
                role = "other"
            attempt = attrs.get("pipeline.stage.attempt", attrs.get("stage.attempt"))
            try:
                attempt = int(attempt) if attempt is not None else None
            except (TypeError, ValueError):
                attempt = None
            error_type = attrs.get("error.type")
            if error_type is None:
                error_type = next((event.get("attributes", {}).get("exception.type")
                                   for event in span_data.get("events", [])
                                   if event.get("name") == "exception"), None)
            events = [{"name": event["name"], "timestamp": event["timestamp"].isoformat(),
                       "attributes": event.get("attributes", {})}
                      for event in span_data.get("events", [])]
            links = span_data.get("links", [])
            values = {
                "execution_id": execution_id,
                "parent_span_id": span_data.get("parent_span_id"),
                "name": span_data["operation_name"],
                "kind": span_data["kind"],
                "role": role,
                "stage_name": attrs.get("pipeline.stage.name", attrs.get("stage.name")),
                "item_id": attrs.get("pipeline.stage.item_id"),
                "attempt": attempt,
                "status": span_data["status_code"],
                "status_message": span_data.get("status_message"),
                "error_type": str(error_type)[:255] if error_type is not None else None,
                "error_class": attrs.get("pipeline.error.class", attrs.get("error.class")),
                "start_time": span_data["start_time"],
                "end_time": span_data.get("end_time"),
                "attrs": span_data.get("attributes", {}),
                "events": events,
                "links": links,
                "resource": resource_attrs,
                "dropped_attributes": span_data.get("dropped_attributes", 0),
                "dropped_events": span_data.get("dropped_events", 0),
            }
            span_record = db.query(SpanRecord).filter_by(trace_id=trace_id, span_id=span_data["span_id"]).first()
            if span_record is None:
                db.add(SpanRecord(trace_id=trace_id, span_id=span_data["span_id"], **values))
            else:
                for key, value in values.items():
                    setattr(span_record, key, value)

        role_values = [
            normalize([{"span_id": span.get("span_id"), "trace_id": trace_id,
                        "attrs": span.get("attributes", {}),
                        "resource": {"attributes": resource_attrs}}])[0]["attrs"].get("autopsy.role")
            for span in trace_item["spans"]
        ]
        last_span_at = max(
            (span.get("end_time") or span.get("start_time") for span in trace_item["spans"]),
            default=trace_item["end_time"] or trace_item["start_time"],
        )
        schedule_diagnosis(
            db,
            execution,
            has_run_span="execution" in role_values,
            last_span_at=last_span_at,
        )

    def ingest_otlp_payload(self, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
        """
        Parses OTLP ExportTraceServiceRequest payload and persists normalized records into DB.

        Args:
            payload: Raw OTLP JSON payload.
            db: Active SQLAlchemy Session.

        Returns:
            Dict containing ingestion statistics (pipelines, executions, traces, spans, events persisted).
        """
        normalized_traces, rejected_spans = self.adapter.parse_with_rejections(payload)

        for trace_item in normalized_traces:
            self._upsert_v2_records(trace_item, db)

        db.commit()
        persisted_traces = [trace["trace_id"] for trace in normalized_traces]
        return {
            "status": "success",
            "traces_processed": len(normalized_traces),
            "spans_persisted": sum(len(trace["spans"]) for trace in normalized_traces),
            "events_persisted": sum(len(span.get("events", []))
                                     for trace in normalized_traces for span in trace["spans"]),
            "trace_ids": persisted_traces,
            "rejected_spans": rejected_spans,
        }
