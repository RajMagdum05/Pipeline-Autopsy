import contextlib
from typing import Dict, List, Optional, Union
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.telemetry.attributes import (
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_VERSION,
    EXECUTION_ENTITY_ID,
    EXECUTION_ID,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    STAGE_NAME,
    STAGE_STATUS,
    STAGE_VERSION,
    ERROR_MESSAGE,
    ERROR_TYPE,
    RETRY_COUNT,
    RETRY_REASON,
)


@contextlib.contextmanager
def stage_span(
    tracer: trace.Tracer,
    stage_name: str,
    execution_id: str,
    entity_id: str,
    span_name: Optional[str] = None,
    input_artifact_ids: Optional[List[str]] = None,
    extra_attributes: Optional[Dict[str, Union[str, int, float, bool, List[str]]]] = None,
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
    pipeline_version: str = DEFAULT_PIPELINE_VERSION,
    stage_version: str = "1.0.0",
    retry_count: Optional[int] = None,
    retry_reason: Optional[str] = None,
    safe_error_message: Optional[str] = None,
):
    """
    Context manager that wraps stage execution in an OpenTelemetry span
    with all required contract attributes set according to TRACE_CONTRACT.md.
    """
    with tracer.start_as_current_span(span_name or stage_name) as span:
        # Set Universal Contract Attributes
        span.set_attribute(PIPELINE_NAME, pipeline_name)
        span.set_attribute(PIPELINE_VERSION, pipeline_version)
        span.set_attribute(EXECUTION_ID, execution_id)
        span.set_attribute(EXECUTION_ENTITY_ID, str(entity_id))
        span.set_attribute(STAGE_NAME, stage_name)
        span.set_attribute(STAGE_VERSION, stage_version)
        span.set_attribute(STAGE_STATUS, "running")
        span.set_attribute(INPUT_ARTIFACT_IDS, input_artifact_ids or [])
        span.set_attribute(OUTPUT_ARTIFACT_IDS, [])

        if retry_count is not None:
            span.set_attribute(RETRY_COUNT, retry_count)
        if retry_reason is not None:
            span.set_attribute(RETRY_REASON, retry_reason)

        # Set any extra attributes passed
        if extra_attributes:
            for k, v in extra_attributes.items():
                if v is not None:
                    span.set_attribute(k, v)

        try:
            yield span
            # If no exception occurred, mark stage status as success
            # Respect explicit stage outcomes set by validators and decision gates.
            if span.attributes.get(STAGE_STATUS) == "running":
                span.set_attribute(STAGE_STATUS, "success")
            if span.status.status_code != StatusCode.ERROR:
                span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            error_message = safe_error_message or str(exc) or type(exc).__name__
            span.set_attribute(STAGE_STATUS, "failed")
            span.set_attribute(ERROR_TYPE, type(exc).__name__)
            span.set_attribute(ERROR_MESSAGE, error_message)
            span.set_status(Status(StatusCode.ERROR, description=error_message))
            if safe_error_message is not None:
                span.add_event(
                    "exception",
                    {
                        "exception.type": type(exc).__name__,
                        "exception.message": error_message,
                        "exception.escaped": True,
                    },
                )
            else:
                span.record_exception(exc)
            raise
