"""In-memory trace capture and a vendored v3 contract assertion helper."""
from copy import deepcopy
from dataclasses import dataclass
from typing import List, Optional

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from .api import _PROVIDER


@dataclass
class Observation:
    family: str
    code: str
    result: str
    stage: Optional[str]
    detail: str
    span_id: Optional[str] = None
    artifact_id: Optional[str] = None
    field: Optional[str] = None
    reported_by: Optional[str] = None
    error_class: Optional[str] = None
    source_artifact_id: Optional[str] = None
    id: str = ""


REQUIRED_ALL = ["pipeline.name", "pipeline.version", "execution.id", "autopsy.role"]
REQUIRED_STAGE = ["stage.name", "stage.status", "stage.attempt", "input.artifact_ids", "output.artifact_ids"]
VALID_STATUS = {"success", "failed", "partial", "skipped"}


ALIASES = {
    "pipeline.run.id": "execution.id",
    "pipeline.entity.id": "execution.entity_id",
    "pipeline.stage.name": "stage.name",
    "pipeline.stage.status": "stage.status",
    "pipeline.stage.attempt": "stage.attempt",
    "pipeline.artifact.input_ids": "input.artifact_ids",
    "pipeline.artifact.output_ids": "output.artifact_ids",
    "pipeline.span.role": "autopsy.role",
    "pipeline.error.class": "error.class",
}
CHECK_PREFIX = "pipeline.check."
INTERNAL_CHECK_PREFIX = "check."


def _attributes(container):
    if not isinstance(container, dict):
        return {}
    attrs = container.get("attributes")
    return attrs if isinstance(attrs, dict) else container


def _run_id(span):
    attrs = span.get("attrs", {})
    resource = _attributes(span.get("resource"))
    for source in (attrs, resource):
        for key in ("pipeline.run.id", "execution.id"):
            if key in source and source[key] not in (None, ""):
                return source[key]
    trace_id = span.get("trace_id", span.get("traceId"))
    if trace_id is None and isinstance(span.get("context"), dict):
        trace_id = span["context"].get("trace_id") or span["context"].get("traceId")
    return f"trace:{trace_id}" if trace_id is not None else None


def _normalize_event(event):
    normalized = deepcopy(event)
    if normalized.get("name") == "pipeline.check":
        normalized["name"] = "autopsy.check"
    attrs = normalized.get("attrs")
    if isinstance(attrs, dict):
        converted = {}
        for key, value in attrs.items():
            target = INTERNAL_CHECK_PREFIX + key[len(CHECK_PREFIX):] if key.startswith(CHECK_PREFIX) else key
            if target not in converted or key.startswith(CHECK_PREFIX):
                converted[target] = value
        normalized["attrs"] = converted
    return normalized


def normalize(spans):
    """Return copied spans with v1 internal keys, accepting both v1 and v3 input."""
    normalized = deepcopy(spans)
    for span in normalized:
        attrs = span.get("attrs")
        if not isinstance(attrs, dict):
            attrs = {}
            span["attrs"] = attrs
        for current, internal in ALIASES.items():
            if current in attrs:
                attrs[internal] = attrs[current]
        run_id = _run_id(span)
        if run_id is not None:
            attrs["execution.id"] = run_id
        span["events"] = [_normalize_event(event) for event in span.get("events", [])]
    return normalized


def validate_trace(spans, manifest):
    # ``diagnose`` normalizes first; this validator consumes that internal shape.
    obs: List[Observation] = []
    grade = "A"

    def lower(to):
        nonlocal grade
        if to > grade:
            grade = to

    ids = {s["span_id"] for s in spans}
    roots = [s for s in spans if s["attrs"].get("autopsy.role") == "execution"]
    if len(roots) != 1:
        obs.append(Observation("structural", "execution_span_count", "fail", None,
                               f"expected exactly 1 execution span, found {len(roots)}"))
        lower("C")
    item_scoped = {st["name"] for st in manifest.get("stages", []) if st.get("scope") == "item"}
    if item_scoped and roots and "pipeline.run.items" not in roots[0]["attrs"]:
        obs.append(Observation("structural", "missing_run_items", "warn", None,
                               "run span is missing pipeline.run.items", span_id=roots[0]["span_id"]))
        lower("B")
    for s in spans:
        a = s["attrs"]
        missing = [k for k in REQUIRED_ALL if k not in a]
        if missing:
            obs.append(Observation("structural", "missing_required_attribute", "fail", a.get("stage.name"),
                                   f"span {s['span_id']} missing {missing}", span_id=s["span_id"]))
            lower("C")
        if s.get("parent") and s["parent"] not in ids:
            obs.append(Observation("structural", "orphan_span", "warn", a.get("stage.name"),
                                   f"span {s['span_id']} parent {s['parent']} not in trace", span_id=s["span_id"]))
            lower("B")
        if a.get("autopsy.role") == "stage":
            miss = [k for k in REQUIRED_STAGE if k not in a]
            if a.get("stage.name") in item_scoped and "pipeline.stage.item_id" not in a:
                miss.append("pipeline.stage.item_id")
            if "stage.name" in miss or "stage.status" in miss:
                obs.append(Observation("structural", "missing_stage_identity", "fail", None,
                                       f"stage span {s['span_id']} missing {miss}", span_id=s["span_id"]))
                lower("C")
            elif miss:
                obs.append(Observation("structural", "missing_stage_attribute", "warn", a["stage.name"],
                                       f"stage span {s['span_id']} missing {miss}", span_id=s["span_id"]))
                lower("B")
            if a.get("stage.status") not in VALID_STATUS | {None}:
                obs.append(Observation("structural", "invalid_stage_status", "warn", a.get("stage.name"),
                                       f"stage.status={a.get('stage.status')!r}", span_id=s["span_id"]))
                lower("B")
            known = {st["name"] for st in manifest["stages"]}
            if a.get("stage.name") and a["stage.name"] not in known:
                obs.append(Observation("structural", "unknown_stage", "warn", a["stage.name"],
                                       "stage not declared in manifest", span_id=s["span_id"]))
                lower("B")
    parent = {s["span_id"]: s.get("parent") for s in spans}
    for sid in parent:
        seen, cur = set(), sid
        while cur:
            if cur in seen:
                obs.append(Observation("structural", "span_cycle", "fail", None, f"cycle through span {sid}"))
                lower("C")
                break
            seen.add(cur)
            cur = parent.get(cur)
    return grade, obs


def _to_contract_spans(readable_spans):
    converted = []
    for span in readable_spans:
        parent = span.parent.span_id if span.parent is not None else None
        converted.append({
            "span_id": f"{span.context.span_id:016x}",
            "trace_id": f"{span.context.trace_id:032x}",
            "parent": f"{parent:016x}" if parent is not None else None,
            "name": span.name,
            "status": "ERROR" if span.status.status_code.name == "ERROR" else "OK",
            "attrs": dict(span.attributes),
            "events": [{"name": event.name, "attrs": dict(event.attributes)} for event in span.events],
        })
    return converted


def assert_contract(spans, manifest):
    """Raise if a span batch violates the vendored structural contract; return its grade."""
    grade, observations = validate_trace(normalize(_to_contract_spans(spans)), manifest)
    if grade != "A":
        details = "; ".join(obs.detail for obs in observations)
        raise AssertionError(f"trace contract grade {grade}: {details}")
    return grade


class InMemoryCapture:
    """Capture SDK spans without setting or replacing the process-global provider."""
    def __init__(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self._token = None

    def __enter__(self):
        self._token = _PROVIDER.set(self.provider)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._token is not None:
            _PROVIDER.reset(self._token)
            self._token = None
        self.provider.shutdown()

    @property
    def spans(self):
        return self.exporter.get_finished_spans()
