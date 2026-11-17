from datetime import datetime, timezone
import base64
import binascii
from typing import Any, Dict, List, Optional, Tuple

from autopsy.core.normalize import normalize


def _parse_otlp_value(val_obj: Any) -> Any:
    """Helper to unwrap OTLP AttributeValue union types into plain Python values."""
    if not isinstance(val_obj, dict):
        return val_obj

    if "stringValue" in val_obj:
        return val_obj["stringValue"]
    elif "intValue" in val_obj:
        try:
            return int(val_obj["intValue"])
        except (ValueError, TypeError):
            return val_obj["intValue"]
    elif "doubleValue" in val_obj:
        try:
            return float(val_obj["doubleValue"])
        except (ValueError, TypeError):
            return val_obj["doubleValue"]
    elif "boolValue" in val_obj:
        return bool(val_obj["boolValue"])
    elif "arrayValue" in val_obj:
        values = val_obj.get("arrayValue", {}).get("values", [])
        return [_parse_otlp_value(v) for v in values]
    elif "kvlistValue" in val_obj:
        values = val_obj.get("kvlistValue", {}).get("values", [])
        return {item.get("key"): _parse_otlp_value(item.get("value")) for item in values if "key" in item}

    # Direct value or fallback
    return list(val_obj.values())[0] if val_obj else None


def _parse_attributes(attrs_list: Any) -> Dict[str, Any]:
    """Converts OTLP KeyValue list [{'key': 'k', 'value': {...}}] to dict."""
    if isinstance(attrs_list, dict):
        return attrs_list
    if not isinstance(attrs_list, list):
        return {}

    parsed = {}
    for attr in attrs_list:
        if isinstance(attr, dict) and "key" in attr:
            k = attr["key"]
            v = _parse_otlp_value(attr.get("value"))
            parsed[k] = v
    return parsed


def _parse_hex_id(id_val: Any, expected_bytes: int) -> Optional[str]:
    """Decode OTLP JSON/protobuf IDs and strictly validate their wire length."""
    if isinstance(id_val, bytes):
        decoded = id_val
    elif isinstance(id_val, str):
        if not id_val:
            return None
        expected_hex_length = expected_bytes * 2
        if len(id_val) == expected_hex_length and all(char in "0123456789abcdefABCDEF" for char in id_val):
            return id_val.lower()
        try:
            decoded = base64.b64decode(id_val, validate=True)
        except (binascii.Error, ValueError):
            return None
    else:
        return None
    if len(decoded) != expected_bytes:
        return None
    return decoded.hex()


def _parse_timestamp(time_val: Any) -> datetime:
    """Converts nanoseconds / milliseconds / ISO string to UTC datetime."""
    if not time_val:
        return datetime.now(timezone.utc)
    if isinstance(time_val, (int, float)):
        # Nanoseconds (19 digits)
        if time_val > 1e16:
            sec = time_val / 1e9
        elif time_val > 1e11:  # Milliseconds
            sec = time_val / 1e3
        else:
            sec = time_val
        return datetime.fromtimestamp(sec, tz=timezone.utc)
    if isinstance(time_val, str):
        if time_val.isdigit():
            return _parse_timestamp(int(time_val))
        try:
            return datetime.fromisoformat(time_val.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _parse_span_kind(kind_val: Any) -> str:
    kind_map = {
        0: "UNSPECIFIED",
        1: "INTERNAL",
        2: "SERVER",
        3: "CLIENT",
        4: "PRODUCER",
        5: "CONSUMER",
    }
    if isinstance(kind_val, int):
        return kind_map.get(kind_val, "INTERNAL")
    if isinstance(kind_val, str):
        val_upper = kind_val.upper().replace("SPAN_KIND_", "")
        return val_upper if val_upper in kind_map.values() else "INTERNAL"
    return "INTERNAL"


def _parse_status_code(status_obj: Any) -> Tuple[str, Optional[str]]:
    if not isinstance(status_obj, dict):
        return ("UNSET", None)
    code_val = status_obj.get("code")
    msg = status_obj.get("message")

    code_map = {0: "UNSET", 1: "OK", 2: "ERROR"}
    if isinstance(code_val, int):
        return (code_map.get(code_val, "UNSET"), msg)
    if isinstance(code_val, str):
        val_upper = code_val.upper().replace("STATUS_CODE_", "")
        return (val_upper if val_upper in code_map.values() else "UNSET", msg)
    return ("UNSET", msg)


def _parse_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


class OTLPAdapter:
    """
    Isolated OTLP Ingestion Adapter.

    Transforms raw OTLP/HTTP ExportTraceServiceRequest JSON payloads into
    clean internal domain structures for normalization and persistence.
    """

    def parse_trace_request(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Compatibility method returning only accepted trace groups."""
        traces, _rejected = self.parse_with_rejections(payload)
        return traces

    def parse_with_rejections(self, payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Parses an OTLP/HTTP ExportTraceServiceRequest payload into a list of normalized
        trace execution structures.

        Returns list of dicts:
            [
              {
                "service_name": "...",
                "execution_id": "...",
                "trace_id": "...",
                "root_span_id": "...",
                "start_time": datetime,
                "end_time": datetime,
                "duration_ms": float,
                "resource_attributes": {...},
                "spans": [
                   {
                     "span_id": "...",
                     "parent_span_id": "...",
                     "service_name": "...",
                     "operation_name": "...",
                     "kind": "...",
                     "start_time": datetime,
                     "end_time": datetime,
                     "duration_ms": float,
                     "status_code": "...",
                     "status_message": "...",
                     "attributes": {...},
                     "events": [
                        {"name": "...", "timestamp": datetime, "attributes": {...}}
                     ]
                   }
                ]
              }
            ]
        """
        resource_spans = payload.get("resourceSpans", [])
        if not resource_spans and "resource_spans" in payload:
            resource_spans = payload.get("resource_spans", [])

        normalized_traces: List[Dict[str, Any]] = []
        rejected_spans = 0

        for res_span in resource_spans:
            res_obj = res_span.get("resource", {})
            res_attrs = _parse_attributes(res_obj.get("attributes", []))

            service_name = (
                res_attrs.get("service.name")
                or res_attrs.get("service_name")
                or "default-service"
            )
            project_id = (
                res_attrs.get("project.id")
                or res_attrs.get("project_id")
                or res_attrs.get("autopsy.project_id")
                or res_attrs.get("customer.id")
                or res_attrs.get("tenant_id")
                or "default"
            )

            scope_spans = res_span.get("scopeSpans", [])
            if not scope_spans and "scope_spans" in res_span:
                scope_spans = res_span.get("scope_spans", [])
            if not scope_spans and "instrumentationLibrarySpans" in res_span:
                scope_spans = res_span.get("instrumentationLibrarySpans", [])

            for scope_span in scope_spans:
                spans_list = scope_span.get("spans", [])

                # Group spans by trace_id
                traces_by_id: Dict[str, List[Dict[str, Any]]] = {}

                for s_obj in spans_list:
                    if not isinstance(s_obj, dict):
                        rejected_spans += 1
                        continue
                    raw_trace_id = _parse_hex_id(s_obj.get("traceId") or s_obj.get("trace_id"), 16)
                    raw_span_id = _parse_hex_id(s_obj.get("spanId") or s_obj.get("span_id"), 8)
                    parent_value = s_obj.get("parentSpanId") or s_obj.get("parent_span_id")
                    raw_parent_id = None if parent_value in (None, "") else _parse_hex_id(parent_value, 8)

                    if not raw_trace_id or not raw_span_id or (parent_value not in (None, "") and not raw_parent_id):
                        rejected_spans += 1
                        continue

                    start_dt = _parse_timestamp(s_obj.get("startTimeUnixNano") or s_obj.get("start_time_unix_nano"))
                    end_dt = _parse_timestamp(s_obj.get("endTimeUnixNano") or s_obj.get("end_time_unix_nano"))
                    dur_ms = (end_dt - start_dt).total_seconds() * 1000.0 if end_dt and start_dt else None

                    status_code, status_msg = _parse_status_code(s_obj.get("status", {}))
                    span_kind = _parse_span_kind(s_obj.get("kind"))
                    op_name = s_obj.get("name") or s_obj.get("operationName") or "unnamed_operation"

                    span_attrs = _parse_attributes(s_obj.get("attributes", []))
                    normalized_span = normalize([{
                        "span_id": raw_span_id,
                        "trace_id": raw_trace_id,
                        "attrs": span_attrs,
                        "resource": {"attributes": res_attrs},
                    }])[0]
                    resolved_execution_id = normalized_span["attrs"]["execution.id"]

                    # Parse Events
                    events_list = []
                    for ev_obj in s_obj.get("events", []):
                        ev_name = ev_obj.get("name", "unnamed_event")
                        ev_time = _parse_timestamp(ev_obj.get("timeUnixNano") or ev_obj.get("time_unix_nano"))
                        ev_attrs = _parse_attributes(ev_obj.get("attributes", []))
                        events_list.append(
                            {"name": ev_name, "timestamp": ev_time, "attributes": ev_attrs}
                        )

                    links_list = []
                    for link_obj in s_obj.get("links", []):
                        if not isinstance(link_obj, dict):
                            continue
                        link_trace_id = _parse_hex_id(link_obj.get("traceId") or link_obj.get("trace_id"), 16)
                        link_span_id = _parse_hex_id(link_obj.get("spanId") or link_obj.get("span_id"), 8)
                        if link_trace_id and link_span_id:
                            links_list.append({
                                "trace_id": link_trace_id,
                                "span_id": link_span_id,
                                "trace_state": link_obj.get("traceState") or link_obj.get("trace_state"),
                                "attributes": _parse_attributes(link_obj.get("attributes", [])),
                                "dropped_attributes": _parse_count(
                                    link_obj.get("droppedAttributesCount", link_obj.get("dropped_attributes_count"))
                                ),
                            })

                    span_record = {
                        "span_id": raw_span_id,
                        "parent_span_id": raw_parent_id,
                        "execution_id": resolved_execution_id,
                        "service_name": service_name,
                        "operation_name": op_name,
                        "kind": span_kind,
                        "start_time": start_dt,
                        "end_time": end_dt,
                        "duration_ms": max(0.0, dur_ms) if dur_ms is not None else None,
                        "status_code": status_code,
                        "status_message": status_msg,
                        "attributes": span_attrs,
                        "events": events_list,
                        "links": links_list,
                        "dropped_attributes": _parse_count(
                            s_obj.get("droppedAttributesCount", s_obj.get("dropped_attributes_count"))
                        ),
                        "dropped_events": _parse_count(
                            s_obj.get("droppedEventsCount", s_obj.get("dropped_events_count"))
                        ),
                    }

                    if raw_trace_id not in traces_by_id:
                        traces_by_id[raw_trace_id] = []
                    traces_by_id[raw_trace_id].append(span_record)

                for t_id, spans in traces_by_id.items():
                    # Find root span (parent_span_id is None or empty)
                    root_span = next((s for s in spans if not s["parent_span_id"]), spans[0] if spans else None)
                    root_span_id = root_span["span_id"] if root_span else None

                    start_times = [s["start_time"] for s in spans if s.get("start_time")]
                    end_times = [s["end_time"] for s in spans if s.get("end_time")]
                    trace_start = min(start_times) if start_times else datetime.now(timezone.utc)
                    trace_end = max(end_times) if end_times else None
                    trace_dur = (trace_end - trace_start).total_seconds() * 1000.0 if trace_end else None

                    # The core normalizer resolves span v3/v1 attrs, then resource attrs,
                    # then the explicit trace:<hex-id> fallback.
                    actual_exec_id = next(
                        (span["execution_id"] for span in spans if span.get("parent_span_id") is None),
                        spans[0]["execution_id"],
                    )

                    normalized_traces.append(
                        {
                            "project_id": project_id,
                            "service_name": service_name,
                            "execution_id": actual_exec_id,
                            "trace_id": t_id,
                            "root_span_id": root_span_id,
                            "start_time": trace_start,
                            "end_time": trace_end,
                            "duration_ms": trace_dur,
                            "resource_attributes": res_attrs,
                            "spans": spans,
                        }
                    )

        return normalized_traces, rejected_spans
