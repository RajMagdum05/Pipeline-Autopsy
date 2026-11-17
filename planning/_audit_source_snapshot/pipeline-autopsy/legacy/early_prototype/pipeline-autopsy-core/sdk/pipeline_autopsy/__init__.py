"""
pipeline_autopsy — the connector.

    import pipeline_autopsy as autopsy

    autopsy.attach(api_key="pa_live_7f2c9e1a", pipeline="insurance-claims-v1")

    @autopsy.trace_step("extraction")
    def extract(ocr_output: dict) -> dict:
        ...
        return fields

    with autopsy.execution(claim_id="CLM-2841"):
        ocr_out = run_ocr(claim)
        fields = extract(ocr_out)
        ...

Until attach() is called, every @trace_step function behaves exactly like
the undecorated function — no network calls, no overhead, no behavior
change. That's deliberate: connecting Pipeline Autopsy should never be
able to change what the enterprise pipeline does, only what you can see.
"""
from __future__ import annotations

import functools
import time
from typing import Any, Callable, Optional, TypeVar

from .client import Client
from .context import current_claim_id, current_execution_id, execution, next_step_index
from .schema import TraceEvent

__all__ = ["attach", "is_attached", "execution", "trace_step"]

F = TypeVar("F", bound=Callable[..., Any])

_client: Optional[Client] = None
_pipeline_name: Optional[str] = None


def attach(api_key: str, pipeline: str, collector_url: str = "http://localhost:8000") -> None:
    """Point the SDK at a running collector. Call this once, at startup."""
    global _client, _pipeline_name
    _client = Client(collector_url=collector_url, api_key=api_key)
    _pipeline_name = pipeline


def is_attached() -> bool:
    return _client is not None


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {"value": value}


def trace_step(name: str, final: bool = False) -> Callable[[F], F]:
    """Decorator: report this step to Pipeline Autopsy every time it runs."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if _client is None:
                return fn(*args, **kwargs)  # not attached — pass straight through

            exec_id = current_execution_id()
            claim_id = current_claim_id()
            if exec_id is None or claim_id is None:
                raise RuntimeError(
                    f"@trace_step('{name}') called outside an autopsy.execution(...) block. "
                    "Wrap the pipeline run: `with autopsy.execution(claim_id=...):`"
                )

            step_input = _as_dict(args[0]) if args else _as_dict(kwargs)
            started_at = time.time()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised below, we just observe it first
                event = TraceEvent(
                    execution_id=exec_id,
                    claim_id=claim_id,
                    pipeline=_pipeline_name or "unknown",
                    step=name,
                    step_index=next_step_index(),
                    is_final_step=final,
                    started_at=started_at,
                    ended_at=time.time(),
                    status="error",
                    error=str(exc),
                    input=step_input,
                    output={},
                )
                _client.send(event)
                raise
            else:
                event = TraceEvent(
                    execution_id=exec_id,
                    claim_id=claim_id,
                    pipeline=_pipeline_name or "unknown",
                    step=name,
                    step_index=next_step_index(),
                    is_final_step=final,
                    started_at=started_at,
                    ended_at=time.time(),
                    status="ok",
                    input=step_input,
                    output=_as_dict(result),
                )
                _client.send(event)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator
