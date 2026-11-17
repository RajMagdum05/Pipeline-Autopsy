from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from autopsy.detectors.base import BaseDetector
from autopsy.detectors.finding import Finding
from autopsy.services.reconstruction_service import ExecutionGraph, ExecutionNode


class ErrorStatusDetector(BaseDetector):
    """
    Detects spans whose status code explicitly indicates an error (e.g. status_code == 'ERROR' or '2').
    """

    @property
    def detector_name(self) -> str:
        return "ErrorStatusDetector"

    def detect(self, graph: ExecutionGraph) -> List[Finding]:
        findings: List[Finding] = []

        def inspect_node(node: ExecutionNode):
            status_upper = str(node.status_code).upper()
            if status_upper in ("ERROR", "2", "STATUS_CODE_ERROR"):
                findings.append(
                    Finding(
                        finding_type="SPAN_ERROR_STATUS",
                        execution_id=graph.execution_id,
                        trace_id=graph.trace_id,
                        span_id=node.span_id,
                        service_name=node.service_name,
                        operation_name=node.operation_name,
                        severity="ERROR",
                        observed_at=node.start_time or datetime.now(timezone.utc),
                        description=f"Span '{node.operation_name}' failed with status code '{node.status_code}' and message '{node.status_message or 'N/A'}'.",
                        evidence_type="SPAN_STATUS",
                        detector_name=self.detector_name,
                        evidence_data={
                            "status_code": node.status_code,
                            "status_message": node.status_message,
                            "attributes": node.attributes,
                        },
                    )
                )
            for child in node.children:
                inspect_node(child)

        for root in graph.root_nodes:
            inspect_node(root)
        for orphan in graph.orphan_nodes:
            inspect_node(orphan)

        return findings


class ExceptionDetector(BaseDetector):
    """
    Detects exception events or exception attributes attached to spans.
    """

    @property
    def detector_name(self) -> str:
        return "ExceptionDetector"

    def detect(self, graph: ExecutionGraph) -> List[Finding]:
        findings: List[Finding] = []

        def inspect_node(node: ExecutionNode):
            # 1. Inspect events for exception events
            for ev in node.events:
                ev_name_lower = str(ev.get("name", "")).lower()
                attrs = ev.get("attributes", {})
                if ev_name_lower in ("exception", "error") or any(k.startswith("exception.") for k in attrs):
                    exc_type = attrs.get("exception.type", attrs.get("error.type", "Exception"))
                    exc_msg = attrs.get("exception.message", attrs.get("error.message", "Exception occurred"))
                    exc_stack = attrs.get("exception.stacktrace")

                    findings.append(
                        Finding(
                            finding_type="EXCEPTION_EVENT",
                            execution_id=graph.execution_id,
                            trace_id=graph.trace_id,
                            span_id=node.span_id,
                            service_name=node.service_name,
                            operation_name=node.operation_name,
                            severity="CRITICAL" if "Fatal" in str(exc_type) else "ERROR",
                            observed_at=node.start_time or datetime.now(timezone.utc),
                            description=f"Exception '{exc_type}' recorded in span '{node.operation_name}': {exc_msg}",
                            evidence_type="EXCEPTION_DATA",
                            detector_name=self.detector_name,
                            evidence_data={
                                "event_name": ev.get("name"),
                                "exception_type": exc_type,
                                "exception_message": exc_msg,
                                "stacktrace_snippet": str(exc_stack)[:500] if exc_stack else None,
                                "attributes": attrs,
                            },
                        )
                    )

            # 2. Inspect attributes for exception indicators
            node_attrs = node.attributes or {}
            if any(k.startswith("exception.") for k in node_attrs):
                exc_type = node_attrs.get("exception.type", "Exception")
                exc_msg = node_attrs.get("exception.message", "Exception attribute present")
                findings.append(
                    Finding(
                        finding_type="EXCEPTION_EVENT",
                        execution_id=graph.execution_id,
                        trace_id=graph.trace_id,
                        span_id=node.span_id,
                        service_name=node.service_name,
                        operation_name=node.operation_name,
                        severity="ERROR",
                        observed_at=node.start_time or datetime.now(timezone.utc),
                        description=f"Exception attribute '{exc_type}' attached to span '{node.operation_name}': {exc_msg}",
                        evidence_type="EXCEPTION_DATA",
                        detector_name=self.detector_name,
                        evidence_data={
                            "exception_type": exc_type,
                            "exception_message": exc_msg,
                            "attributes": node_attrs,
                        },
                    )
                )

            for child in node.children:
                inspect_node(child)

        for root in graph.root_nodes:
            inspect_node(root)
        for orphan in graph.orphan_nodes:
            inspect_node(orphan)

        return findings


class TimeoutDetector(BaseDetector):
    """
    Detects duration anomalies or explicit timeout telemetry indicators.
    Allows optional threshold rules.
    """

    def __init__(self, threshold_rules_ms: Optional[Dict[str, float]] = None):
        """
        Args:
            threshold_rules_ms: Optional mapping from operation_name or service_name to max allowed ms.
        """
        self.threshold_rules_ms = threshold_rules_ms or {}

    @property
    def detector_name(self) -> str:
        return "TimeoutDetector"

    def detect(self, graph: ExecutionGraph) -> List[Finding]:
        findings: List[Finding] = []

        def inspect_node(node: ExecutionNode):
            node_attrs = node.attributes or {}

            # 1. Explicit timeout telemetry attribute or HTTP 504 Gateway Timeout
            is_timeout_attr = (
                node_attrs.get("timeout_exceeded") is True
                or str(node_attrs.get("error.type", "")).lower() in ("timeout", "timeout_error", "gateway_timeout")
                or str(node_attrs.get("http.status_code")) == "504"
            )

            if is_timeout_attr:
                findings.append(
                    Finding(
                        finding_type="TIMEOUT_EXCEEDED",
                        execution_id=graph.execution_id,
                        trace_id=graph.trace_id,
                        span_id=node.span_id,
                        service_name=node.service_name,
                        operation_name=node.operation_name,
                        severity="ERROR",
                        observed_at=node.start_time or datetime.now(timezone.utc),
                        description=f"Timeout explicitly recorded on span '{node.operation_name}' (duration: {node.duration_ms}ms).",
                        evidence_type="TIMEOUT_METRIC",
                        detector_name=self.detector_name,
                        evidence_data={
                            "duration_ms": node.duration_ms,
                            "attributes": node_attrs,
                        },
                    )
                )

            # 2. Configurable duration threshold breach
            max_allowed = (
                self.threshold_rules_ms.get(node.operation_name)
                or self.threshold_rules_ms.get(node.service_name)
            )

            if max_allowed and node.duration_ms is not None and node.duration_ms > max_allowed:
                findings.append(
                    Finding(
                        finding_type="TIMEOUT_EXCEEDED",
                        execution_id=graph.execution_id,
                        trace_id=graph.trace_id,
                        span_id=node.span_id,
                        service_name=node.service_name,
                        operation_name=node.operation_name,
                        severity="WARNING" if node.status_code != "ERROR" else "ERROR",
                        observed_at=node.start_time or datetime.now(timezone.utc),
                        description=f"Span '{node.operation_name}' duration ({node.duration_ms:.2f}ms) breached configured threshold ({max_allowed:.2f}ms).",
                        evidence_type="TIMEOUT_METRIC",
                        detector_name=self.detector_name,
                        evidence_data={
                            "duration_ms": node.duration_ms,
                            "max_allowed_ms": max_allowed,
                        },
                    )
                )

            for child in node.children:
                inspect_node(child)

        for root in graph.root_nodes:
            inspect_node(root)
        for orphan in graph.orphan_nodes:
            inspect_node(orphan)

        return findings


class DependencyFailureDetector(BaseDetector):
    """
    Detects parent/upstream operations whose child/dependent operations failed.
    Records the upstream -> dependent failure relationship without declaring parent culpability.
    """

    @property
    def detector_name(self) -> str:
        return "DependencyFailureDetector"

    def detect(self, graph: ExecutionGraph) -> List[Finding]:
        findings: List[Finding] = []

        def inspect_node(parent: ExecutionNode):
            for child in parent.children:
                child_failed = (
                    str(child.status_code).upper() in ("ERROR", "2", "STATUS_CODE_ERROR")
                    or any(ev.get("name") in ("exception", "error") for ev in child.events)
                )
                if child_failed:
                    findings.append(
                        Finding(
                            finding_type="DEPENDENCY_FAILURE",
                            execution_id=graph.execution_id,
                            trace_id=graph.trace_id,
                            span_id=parent.span_id,
                            service_name=parent.service_name,
                            operation_name=parent.operation_name,
                            severity="WARNING" if parent.status_code != "ERROR" else "ERROR",
                            observed_at=parent.start_time or datetime.now(timezone.utc),
                            description=f"Upstream operation '{parent.operation_name}' experienced dependency failure in child span '{child.operation_name}' ({child.service_name}).",
                            evidence_type="DEPENDENCY_LINK",
                            detector_name=self.detector_name,
                            evidence_data={
                                "upstream_span_id": parent.span_id,
                                "upstream_operation": parent.operation_name,
                                "failed_dependent_span_id": child.span_id,
                                "failed_dependent_operation": child.operation_name,
                                "dependent_service": child.service_name,
                                "dependent_status_code": child.status_code,
                            },
                        )
                    )
                # Recurse
                inspect_node(child)

        for root in graph.root_nodes:
            inspect_node(root)

        return findings


class StructuralTelemetryDetector(BaseDetector):
    """
    Converts telemetry structural warnings (orphan spans, multiple roots, duplicate IDs) into telemetry findings.
    """

    @property
    def detector_name(self) -> str:
        return "StructuralTelemetryDetector"

    def detect(self, graph: ExecutionGraph) -> List[Finding]:
        findings: List[Finding] = []

        # 1. Structural warnings on ExecutionGraph
        for warn in graph.warnings:
            findings.append(
                Finding(
                    finding_type="STRUCTURAL_WARNING",
                    execution_id=graph.execution_id,
                    trace_id=graph.trace_id,
                    span_id=warn.get("span_id"),
                    service_name="telemetry_ingestion",
                    operation_name="trace_reconstruction",
                    severity="WARNING" if warn.get("code") != "DUPLICATE_SPAN_ID" else "ERROR",
                    observed_at=graph.start_time or datetime.now(timezone.utc),
                    description=f"Telemetry structural warning [{warn.get('code')}]: {warn.get('message')}",
                    evidence_type="STRUCTURAL_WARNING",
                    detector_name=self.detector_name,
                    evidence_data=warn,
                )
            )

        # 2. Orphan nodes
        for orphan in graph.orphan_nodes:
            findings.append(
                Finding(
                    finding_type="STRUCTURAL_WARNING",
                    execution_id=graph.execution_id,
                    trace_id=graph.trace_id,
                    span_id=orphan.span_id,
                    service_name=orphan.service_name,
                    operation_name=orphan.operation_name,
                    severity="WARNING",
                    observed_at=orphan.start_time or datetime.now(timezone.utc),
                    description=f"Orphan span '{orphan.operation_name}' references non-existent parent_span_id '{orphan.parent_span_id}'.",
                    evidence_type="STRUCTURAL_WARNING",
                    detector_name=self.detector_name,
                    evidence_data={
                        "span_id": orphan.span_id,
                        "parent_span_id": orphan.parent_span_id,
                    },
                )
            )

        return findings


class ExplicitValidationDetector(BaseDetector):
    """
    Detects explicit validation failures or schema error events recorded in span events/attributes.
    """

    @property
    def detector_name(self) -> str:
        return "ExplicitValidationDetector"

    def detect(self, graph: ExecutionGraph) -> List[Finding]:
        findings: List[Finding] = []

        def inspect_node(node: ExecutionNode):
            # Check events
            for ev in node.events:
                ev_name_lower = str(ev.get("name", "")).lower()
                if any(term in ev_name_lower for term in ("validation_failed", "schema_error", "assertion_failure", "contract_violation")):
                    findings.append(
                        Finding(
                            finding_type="EXPLICIT_VALIDATION_FAILURE",
                            execution_id=graph.execution_id,
                            trace_id=graph.trace_id,
                            span_id=node.span_id,
                            service_name=node.service_name,
                            operation_name=node.operation_name,
                            severity="ERROR",
                            observed_at=node.start_time or datetime.now(timezone.utc),
                            description=f"Explicit validation failure event '{ev.get('name')}' recorded in span '{node.operation_name}'.",
                            evidence_type="VALIDATION_EVENT",
                            detector_name=self.detector_name,
                            evidence_data={
                                "event_name": ev.get("name"),
                                "attributes": ev.get("attributes", {}),
                            },
                        )
                    )

            # Check attributes
            node_attrs = node.attributes or {}
            if node_attrs.get("validation.error") or node_attrs.get("schema.valid") is False:
                findings.append(
                    Finding(
                        finding_type="EXPLICIT_VALIDATION_FAILURE",
                        execution_id=graph.execution_id,
                        trace_id=graph.trace_id,
                        span_id=node.span_id,
                        service_name=node.service_name,
                        operation_name=node.operation_name,
                        severity="ERROR",
                        observed_at=node.start_time or datetime.now(timezone.utc),
                        description=f"Explicit validation error attribute in span '{node.operation_name}'.",
                        evidence_type="VALIDATION_EVENT",
                        detector_name=self.detector_name,
                        evidence_data={"attributes": node_attrs},
                    )
                )

            for child in node.children:
                inspect_node(child)

        for root in graph.root_nodes:
            inspect_node(root)
        for orphan in graph.orphan_nodes:
            inspect_node(orphan)

        return findings
