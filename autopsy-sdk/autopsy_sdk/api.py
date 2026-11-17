"""Contract-v3 instrumentation built on the OpenTelemetry API."""
import contextvars
import json
import logging
import os
import re
import threading
import uuid
from contextlib import contextmanager
from hashlib import sha256

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .errors import AutopsyUsageError, DataError, GateBlocked

logger = logging.getLogger("autopsy_sdk")
_PIPELINE = {"name": None, "version": None}
_RUN = contextvars.ContextVar("autopsy_run", default=None)
_STAGE = contextvars.ContextVar("autopsy_stage", default=None)
_PROVIDER = contextvars.ContextVar("autopsy_provider_override", default=None)
_ARTIFACT_UPLOADER = None
_WARNED = set()
_WARN_LOCK = threading.Lock()

_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)\+?(?:\d[\s().-]*){7,15}\d?(?!\w)")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{12,16}(?!\d)")
_ERROR_CLASSES = {
    "infra": ("TimeoutError", "ConnectionError", "OSError", "Timeout", "RateLimit", "Unavailable",
              "ResourceExhausted", "ServerError"),
    "data": ("ValueError", "KeyError", "TypeError", "JSONDecodeError", "ValidationError", "DataError",
             "GateBlocked"),
}
_VALID_OUTCOMES = {"success", "failed", "partial", "blocked"}
_VALID_STAGE_STATUSES = {"success", "failed", "partial", "skipped"}


def _enabled():
    return os.getenv("AUTOPSY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _strict():
    return os.getenv("AUTOPSY_STRICT", "false").strip().lower() in {"1", "true", "yes", "on"}


def _warn_internal(where, exc):
    with _WARN_LOCK:
        if where in _WARNED:
            return
        _WARNED.add(where)
    try:
        logger.warning("Autopsy SDK internal error in %s (%s); instrumentation was skipped", where,
                       type(exc).__name__)
    except Exception:
        pass


def _safe(where, fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        _warn_internal(where, exc)
        return default


def _tracer():
    provider = _PROVIDER.get()
    return provider.get_tracer("autopsy_sdk", "2.0.0") if provider is not None else trace.get_tracer("autopsy_sdk", "2.0.0")


def safe_message(message):
    """Mask emails, phone-like values, and 12–16 digit identifiers, then cap length."""
    text = str(message)
    text = _EMAIL.sub("[REDACTED]", text)

    def mask_phone(match):
        digits = sum(char.isdigit() for char in match.group(0))
        return "[REDACTED]" if 7 <= digits <= 15 else match.group(0)

    text = _PHONE.sub(mask_phone, text)
    text = _LONG_NUMBER.sub("[REDACTED]", text)
    return text[:500]


def _error_class(exc, overrides=None):
    if overrides:
        for exception_type, classification in overrides.items():
            try:
                if isinstance(exc, exception_type) and classification in {"infra", "data", "unknown"}:
                    return classification
            except TypeError:
                continue
    name = type(exc).__name__
    module = type(exc).__module__
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if (name in _ERROR_CLASSES["infra"] or any(token in name for token in _ERROR_CLASSES["infra"])
            or (module.startswith("httpx") and name.endswith("TransportError"))
            or (isinstance(status, int) and (status in (408, 429) or 500 <= status <= 599))):
        return "infra"
    if isinstance(exc, (ValueError, KeyError, TypeError, DataError, GateBlocked)) or any(
        token in name for token in _ERROR_CLASSES["data"]
    ):
        return "data"
    return "unknown"


def _record_error(span, exc, overrides=None):
    _safe("record error type", span.set_attribute, "error.type", type(exc).__name__[:128])
    _safe("record error class", span.set_attribute, "pipeline.error.class", _error_class(exc, overrides))
    _safe("record error status", span.set_status, Status(StatusCode.ERROR, safe_message(exc)))


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs):
        return None

    def set_attributes(self, *_args, **_kwargs):
        return None

    def add_event(self, *_args, **_kwargs):
        return None

    def set_status(self, *_args, **_kwargs):
        return None


@contextmanager
def _span_scope(name, attributes):
    if not _enabled():
        yield _NoopSpan()
        return
    manager = None
    try:
        manager = _tracer().start_as_current_span(name, attributes=attributes, record_exception=False,
                                                  set_status_on_exception=False)
        span = manager.__enter__()
    except Exception as exc:
        _warn_internal("start span", exc)
        yield _NoopSpan()
        return
    error_info = None
    try:
        yield span
    except BaseException:
        import sys
        error_info = sys.exc_info()
        raise
    finally:
        try:
            manager.__exit__(*(error_info or (None, None, None)))
        except Exception as exc:
            _warn_internal("end span", exc)


def _current_pipeline():
    return (_PIPELINE["name"] or os.getenv("AUTOPSY_PIPELINE_NAME") or "unknown",
            _PIPELINE["version"] or os.getenv("AUTOPSY_PIPELINE_VERSION") or "0.0.0")


def _set_artifact_uploader(uploader):
    global _ARTIFACT_UPLOADER
    _ARTIFACT_UPLOADER = uploader


def set_pipeline(name=None, version=None):
    """Set the process-wide pipeline identity, or read it from environment."""
    _PIPELINE["name"] = name or os.getenv("AUTOPSY_PIPELINE_NAME") or "unknown"
    _PIPELINE["version"] = version or os.getenv("AUTOPSY_PIPELINE_VERSION") or "0.0.0"
    return _PIPELINE["name"], _PIPELINE["version"]


def artifact_id(kind, content, item_id=None):
    """Compute a contract-v3 content identifier for the active run and item."""
    run = _RUN.get()
    run_id = run.run_id if run is not None else ""
    if isinstance(content, bytes):
        canonical = content
    elif isinstance(content, str):
        canonical = content.encode("utf-8")
    else:
        canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload = (str(run_id).encode("utf-8") + b"\x00" + str(kind).encode("utf-8") + b"\x00"
               + str(item_id or "").encode("utf-8") + b"\x00" + canonical)
    return "art_" + sha256(payload).hexdigest()[:16]


class RunContext:
    def __init__(self, span, run_id, entity_id, pipeline_name, pipeline_version):
        self.raw_span = span
        self.run_id = run_id
        self.entity_id = entity_id
        self.pipeline_name = pipeline_name
        self.pipeline_version = pipeline_version
        self._outcome = None
        self._had_failure = False
        self._had_partial = False

    def _common_attributes(self):
        attrs = {"pipeline.name": self.pipeline_name, "pipeline.version": self.pipeline_version,
                 "pipeline.run.id": self.run_id}
        if self.entity_id is not None:
            attrs["pipeline.entity.id"] = str(self.entity_id)
        return attrs

    def set_outcome(self, outcome):
        if outcome not in _VALID_OUTCOMES:
            raise AutopsyUsageError(f"Invalid run outcome: {outcome!r}")
        self._outcome = outcome


@contextmanager
def run(entity_id=None, items=None, run_id=None, trigger="api", previous_run_id=None):
    if trigger not in {"api", "rerun", "cache_hit", "test"}:
        raise AutopsyUsageError(f"Invalid run trigger: {trigger!r}")
    pipeline_name, pipeline_version = _current_pipeline()
    run_id = str(run_id or uuid.uuid4())
    item_map = items or {}
    item_values = [f"{item}:{role}" for item, role in item_map.items()] if isinstance(item_map, dict) else []
    attributes = {
        "pipeline.name": pipeline_name,
        "pipeline.version": pipeline_version,
        "pipeline.run.id": run_id,
        "pipeline.span.role": "execution",
        "pipeline.run.items": item_values,
        "pipeline.run.trigger": trigger,
        "autopsy.sdk.version": "2.0.0",
        "autopsy.schema.version": "pipeline-trace/3",
    }
    if entity_id is not None:
        attributes["pipeline.entity.id"] = str(entity_id)
    if previous_run_id is not None:
        attributes["pipeline.run.previous_id"] = str(previous_run_id)
    state = None
    token = None
    with _span_scope("pipeline.run", attributes) as span:
        state = RunContext(span, run_id, entity_id, pipeline_name, pipeline_version)
        token = _RUN.set(state)
        thrown = False
        try:
            yield state
        except BaseException as exc:
            thrown = True
            state._had_failure = True
            _record_error(span, exc)
            raise
        finally:
            if state._outcome is not None:
                outcome = state._outcome
            elif thrown or state._had_failure:
                outcome = "failed"
            elif state._had_partial:
                outcome = "partial"
            else:
                outcome = "success"
            _safe("set run outcome", span.set_attribute, "pipeline.run.outcome", outcome)
            if outcome in ("failed", "blocked"):
                _safe("set run status", span.set_status, Status(StatusCode.ERROR, ""))
            else:
                _safe("set run status", span.set_status, Status(StatusCode.OK))
            if token is not None:
                _RUN.reset(token)


class StageContext:
    def __init__(self, span, name, item_id, error_classes):
        self.raw_span = span
        self.name = name
        self.item_id = item_id
        self.error_classes = error_classes
        self._status = None
        self._outputs = []
        self._inputs = []

    def set_status(self, status):
        if status not in _VALID_STAGE_STATUSES:
            raise AutopsyUsageError(f"Invalid stage status: {status!r}")
        self._status = status

    def add_input(self, artifact):
        if artifact not in self._inputs:
            self._inputs.append(artifact)
            _safe("update stage input ids", self.raw_span.set_attribute, "pipeline.artifact.input_ids",
                  list(self._inputs))

    def record_artifact(self, kind, content, item_id=None, excerpt_values=None):
        artifact = artifact_id(kind, content, self.item_id if item_id is None else item_id)
        self._outputs.append(artifact)
        _safe("update stage output ids", self.raw_span.set_attribute, "pipeline.artifact.output_ids",
              list(self._outputs))
        uploader = _ARTIFACT_UPLOADER
        run_state = _RUN.get()
        if uploader is not None and run_state is not None:
            metadata = {
                "id": artifact,
                "execution_id": run_state.run_id,
                "pipeline": run_state.pipeline_name,
                "version": run_state.pipeline_version,
                "stage": self.name,
                "item_id": self.item_id if item_id is None else item_id,
            }
            _safe("enqueue artifact", uploader.enqueue, kind, content, metadata, excerpt_values)
        return artifact

    def check(self, check_id, kind, result, action, target=None, field=None, observed=None, expected=None):
        return check(check_id, kind, result, action, target, field, observed, expected)

    def operation(self, name, attributes=None):
        return operation(name, attributes)


@contextmanager
def stage(name, item_id=None, item_role=None, inputs=None, attempt=1, error_classes=None):
    if _enabled() and _STAGE.get() is not None:
        if _strict():
            raise AutopsyUsageError("Nested stages are not allowed in strict mode")
        with operation(name) as nested:
            yield nested
        return
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise AutopsyUsageError("Stage attempt must be an integer greater than or equal to 1")
    state = _RUN.get()
    attrs = {
        "pipeline.span.role": "stage",
        "pipeline.stage.name": str(name),
        "pipeline.stage.attempt": int(attempt),
        "pipeline.artifact.input_ids": [str(value) for value in (inputs or [])],
        "pipeline.artifact.output_ids": [],
    }
    if state is not None:
        attrs.update(state._common_attributes())
    else:
        pipeline_name, pipeline_version = _current_pipeline()
        attrs.update({"pipeline.name": pipeline_name, "pipeline.version": pipeline_version,
                      "pipeline.run.id": f"orphan-{uuid.uuid4()}"})
    if item_id is not None:
        attrs["pipeline.stage.item_id"] = str(item_id)
    if item_role is not None:
        attrs["pipeline.stage.item_role"] = str(item_role)
    with _span_scope(str(name), attrs) as span:
        context = StageContext(span, str(name), str(item_id) if item_id is not None else None, error_classes)
        token = _STAGE.set(context)
        try:
            yield context
        except BaseException as exc:
            context._status = "failed"
            if state is not None:
                state._had_failure = True
            _record_error(span, exc, error_classes)
            raise
        finally:
            status = context._status or "success"
            _safe("set stage status", span.set_attribute, "pipeline.stage.status", status)
            if status in ("failed", "partial", "skipped"):
                if status == "failed":
                    _safe("set stage status code", span.set_status, Status(StatusCode.ERROR, ""))
                if state is not None:
                    state._had_failure = state._had_failure or status == "failed"
                    state._had_partial = state._had_partial or status in ("partial", "skipped")
            else:
                _safe("set stage status code", span.set_status, Status(StatusCode.OK))
            _STAGE.reset(token)


@contextmanager
def operation(name, attributes=None):
    attrs = {"pipeline.span.role": "operation"}
    if attributes:
        reserved = {"pipeline.span.role", "pipeline.name", "pipeline.version", "pipeline.run.id",
                    "pipeline.entity.id"}
        attrs.update({key: value for key, value in attributes.items() if key not in reserved})
    state = _RUN.get()
    if state is not None:
        attrs.update(state._common_attributes())
    else:
        pipeline_name, pipeline_version = _current_pipeline()
        attrs.setdefault("pipeline.name", pipeline_name)
        attrs.setdefault("pipeline.version", pipeline_version)
        attrs.setdefault("pipeline.run.id", f"orphan-{uuid.uuid4()}")
    with _span_scope(str(name), attrs) as span:
        try:
            yield span
        except BaseException as exc:
            _record_error(span, exc)
            state = _RUN.get()
            if state is not None:
                state._had_failure = True
            raise
        else:
            _safe("set operation status", span.set_status, Status(StatusCode.OK))


def _emit_check(span, check_id, kind, result, action, target, field, observed, expected):
    allowed = {"schema", "threshold", "rule", "grounding", "classification", "safety", "decision_rule"}
    if kind not in allowed:
        raise AutopsyUsageError(f"Invalid check kind: {kind!r}")
    if result not in {"pass", "warn", "fail", "skip"}:
        raise AutopsyUsageError(f"Invalid check result: {result!r}")
    if action not in {"blocked", "continued", "review"}:
        raise AutopsyUsageError(f"Invalid check action: {action!r}")
    attrs = {
        "pipeline.check.id": str(check_id),
        "pipeline.check.kind": kind,
        "pipeline.check.result": result,
        "pipeline.check.action": action,
    }
    optional = {
        "pipeline.check.target_artifact_id": target,
        "pipeline.check.field": field,
        "pipeline.check.observed": observed,
        "pipeline.check.expected": expected,
    }
    attrs.update({key: str(value)[:64] if key.endswith(("observed", "expected")) else str(value)
                  for key, value in optional.items() if value is not None})
    _safe("add check event", span.add_event, "pipeline.check", attrs)


def check(check_id, kind, result, action, target=None, field=None, observed=None, expected=None):
    if not _enabled():
        return None
    active_stage = _STAGE.get()
    if active_stage is None:
        _warn_internal("check outside stage", RuntimeError("no active stage"))
        return None
    try:
        span = trace.get_current_span()
    except Exception as exc:
        _warn_internal("get current span for check", exc)
        return None
    return _emit_check(span, check_id, kind, result, action, target, field, observed, expected)
