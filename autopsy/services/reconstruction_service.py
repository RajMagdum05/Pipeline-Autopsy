from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from autopsy.db.models import TraceModel, SpanModel, EventModel, ExecutionModel


@dataclass
class ExecutionNode:
    """
    Internal normalized representation of a single span/operation within an ExecutionGraph.
    """
    span_id: str
    parent_span_id: Optional[str]
    service_name: str
    operation_name: str
    kind: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_ms: Optional[float]
    status_code: str
    status_message: Optional[str]
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    children: List["ExecutionNode"] = field(default_factory=list)
    is_orphan: bool = False
    is_duplicate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the node tree to a nested dictionary representation."""
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "service_name": self.service_name,
            "operation_name": self.operation_name,
            "kind": self.kind,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status_code": self.status_code,
            "status_message": self.status_message,
            "attributes": self.attributes,
            "events": self.events,
            "is_orphan": self.is_orphan,
            "is_duplicate": self.is_duplicate,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class ExecutionGraph:
    """
    Internal normalized representation of an entire reconstructed pipeline execution tree.
    """
    execution_id: str
    trace_id: str
    root_nodes: List[ExecutionNode] = field(default_factory=list)
    orphan_nodes: List[ExecutionNode] = field(default_factory=list)
    reconstruction_status: str = "COMPLETE"  # COMPLETE, WARNINGS, CORRUPTED
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    total_spans_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the ExecutionGraph to a clean programmatic dictionary."""
        return {
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "reconstruction_status": self.reconstruction_status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "total_spans_count": self.total_spans_count,
            "warnings": self.warnings,
            "root_nodes": [root.to_dict() for root in self.root_nodes],
            "orphan_nodes": [orphan.to_dict() for orphan in self.orphan_nodes],
        }


class PipelineReconstructionEngine:
    """
    Deterministic Pipeline Execution Reconstruction Engine.

    Reconstructs DAG/tree execution graphs from raw span telemetry using
    parent_span_id linkage, timestamp analysis, and structural anomaly validation.
    Zero LLMs or domain-specific assumptions.
    """

    def reconstruct_from_spans(
        self,
        execution_id: str,
        trace_id: str,
        spans_input: List[Any],
    ) -> ExecutionGraph:
        """
        Reconstructs an ExecutionGraph from a list of SpanModel objects or dictionaries.

        Args:
            execution_id: Identifier of the pipeline execution run.
            trace_id: OpenTelemetry trace ID.
            spans_input: List of SQLAlchemy SpanModel instances or raw span dicts.

        Returns:
            ExecutionGraph instance.
        """
        graph = ExecutionGraph(execution_id=execution_id, trace_id=trace_id)
        if not spans_input:
            graph.reconstruction_status = "WARNINGS"
            graph.warnings.append({
                "code": "EMPTY_TRACE",
                "message": f"No spans found for trace_id '{trace_id}'.",
            })
            return graph

        nodes_by_id: Dict[str, ExecutionNode] = {}
        raw_nodes_list: List[ExecutionNode] = []
        seen_span_ids = set()
        duplicate_span_ids = set()

        # Step 1: Convert raw spans into ExecutionNode instances and check for duplicates
        for span_obj in spans_input:
            node = self._normalize_to_node(span_obj)
            raw_nodes_list.append(node)

            if node.span_id in seen_span_ids:
                duplicate_span_ids.add(node.span_id)
                node.is_duplicate = True
            else:
                seen_span_ids.add(node.span_id)
                nodes_by_id[node.span_id] = node

        # Record duplicate span ID warnings
        if duplicate_span_ids:
            graph.reconstruction_status = "WARNINGS"
            for dup_id in duplicate_span_ids:
                graph.warnings.append({
                    "code": "DUPLICATE_SPAN_ID",
                    "message": f"Duplicate span_id '{dup_id}' detected in trace '{trace_id}'.",
                    "span_id": dup_id,
                })

        # Step 2: Build parent-child hierarchy and identify root vs orphan spans
        for node in raw_nodes_list:
            parent_id = node.parent_span_id

            if not parent_id:
                # Root span (no parent)
                graph.root_nodes.append(node)
            elif parent_id in nodes_by_id:
                # Valid parent found
                parent_node = nodes_by_id[parent_id]
                parent_node.children.append(node)
            else:
                # Orphan span (parent ID specified but not present in trace)
                node.is_orphan = True
                graph.orphan_nodes.append(node)
                graph.reconstruction_status = "WARNINGS"
                graph.warnings.append({
                    "code": "ORPHAN_SPAN",
                    "message": f"Span '{node.span_id}' ({node.operation_name}) references non-existent parent_span_id '{parent_id}'.",
                    "span_id": node.span_id,
                    "parent_span_id": parent_id,
                })

        # Step 3: Validate Multiple Roots
        if len(graph.root_nodes) > 1:
            graph.reconstruction_status = "WARNINGS"
            root_ids = [r.span_id for r in graph.root_nodes]
            graph.warnings.append({
                "code": "MULTIPLE_ROOT_SPANS",
                "message": f"Trace contains {len(graph.root_nodes)} root spans: {root_ids}.",
                "root_span_ids": root_ids,
            })

        # Step 4: Sort children of each node chronologically by start_time
        def sort_children_recursively(n: ExecutionNode):
            n.children.sort(key=lambda c: c.start_time if c.start_time else datetime.min)
            for child in n.children:
                sort_children_recursively(child)

        for root in graph.root_nodes:
            sort_children_recursively(root)

        graph.root_nodes.sort(key=lambda r: r.start_time if r.start_time else datetime.min)

        # Step 5: Compute overall graph timing bounds
        all_starts = [n.start_time for n in raw_nodes_list if n.start_time]
        all_ends = [n.end_time for n in raw_nodes_list if n.end_time]
        if all_starts:
            graph.start_time = min(all_starts)
        if all_ends:
            graph.end_time = max(all_ends)
        if graph.start_time and graph.end_time:
            graph.duration_ms = (graph.end_time - graph.start_time).total_seconds() * 1000.0

        graph.total_spans_count = len(raw_nodes_list)
        return graph

    def reconstruct_from_db(self, trace_id: str, db: Session) -> ExecutionGraph:
        """
        Queries database for a given trace_id and reconstructs its ExecutionGraph.
        """
        trace_rec = db.query(TraceModel).filter_by(trace_id=trace_id).first()
        if not trace_rec:
            graph = ExecutionGraph(execution_id="unknown", trace_id=trace_id)
            graph.reconstruction_status = "CORRUPTED"
            graph.warnings.append({
                "code": "TRACE_NOT_FOUND",
                "message": f"Trace with trace_id '{trace_id}' not found in database.",
            })
            return graph

        spans_db = (
            db.query(SpanModel)
            .filter_by(trace_id=trace_id)
            .order_by(SpanModel.start_time)
            .all()
        )

        return self.reconstruct_from_spans(
            execution_id=trace_rec.execution_id,
            trace_id=trace_id,
            spans_input=spans_db,
        )

    def _normalize_to_node(self, span_obj: Any) -> ExecutionNode:
        """Converts an ORM SpanModel instance or dictionary into an ExecutionNode."""
        if isinstance(span_obj, dict):
            events_raw = span_obj.get("events", [])
            events_list = [
                {
                    "name": ev.get("name"),
                    "timestamp": ev.get("timestamp").isoformat() if isinstance(ev.get("timestamp"), datetime) else str(ev.get("timestamp")),
                    "attributes": ev.get("attributes", {}),
                }
                for ev in events_raw
            ]
            return ExecutionNode(
                span_id=str(span_obj.get("span_id")),
                parent_span_id=span_obj.get("parent_span_id"),
                service_name=span_obj.get("service_name", "unknown"),
                operation_name=span_obj.get("operation_name", "unnamed"),
                kind=span_obj.get("kind", "INTERNAL"),
                start_time=span_obj.get("start_time"),
                end_time=span_obj.get("end_time"),
                duration_ms=span_obj.get("duration_ms"),
                status_code=span_obj.get("status_code", "UNSET"),
                status_message=span_obj.get("status_message"),
                attributes=span_obj.get("attributes", {}),
                events=events_list,
            )
        else:
            # SQLAlchemy SpanModel
            events_list = [
                {
                    "name": ev.name,
                    "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
                    "attributes": ev.attributes,
                }
                for ev in getattr(span_obj, "events", [])
            ]
            return ExecutionNode(
                span_id=str(span_obj.span_id),
                parent_span_id=span_obj.parent_span_id,
                service_name=span_obj.service_name,
                operation_name=span_obj.operation_name,
                kind=span_obj.kind,
                start_time=span_obj.start_time,
                end_time=span_obj.end_time,
                duration_ms=span_obj.duration_ms,
                status_code=span_obj.status_code,
                status_message=span_obj.status_message,
                attributes=span_obj.attributes or {},
                events=events_list,
            )
