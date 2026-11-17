"""Normalize current and legacy trace fields into the core's internal shape."""
from copy import deepcopy


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
