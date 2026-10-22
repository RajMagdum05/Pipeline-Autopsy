"""
Tracks "which execution/claim are we currently inside" using contextvars,
so a step function doesn't need execution_id threaded through every call —
it just runs inside an `autopsy.execution(...)` block and picks it up.
"""
from __future__ import annotations

import itertools
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_execution_id: ContextVar[Optional[str]] = ContextVar("execution_id", default=None)
_claim_id: ContextVar[Optional[str]] = ContextVar("claim_id", default=None)
_step_counter: ContextVar[Optional["itertools.count"]] = ContextVar("step_counter", default=None)

_exec_seq = itertools.count(1024)  # cosmetic: makes ids look like EXE-1024, EXE-1025, ...


def current_execution_id() -> Optional[str]:
    return _execution_id.get()


def current_claim_id() -> Optional[str]:
    return _claim_id.get()


def next_step_index() -> int:
    counter = _step_counter.get()
    if counter is None:
        return 0
    return next(counter)


@contextmanager
def execution(claim_id: str, execution_id: Optional[str] = None):
    """
    Marks the start of one pipeline run. Every @trace_step call made while
    inside this block is attributed to the same execution_id automatically.

        with autopsy.execution(claim_id="CLM-2841") as execution_id:
            ocr_output = run_ocr(claim_documents)
            fields = extract(ocr_output)
            ...
    """
    exec_id = execution_id or f"EXE-{next(_exec_seq)}"
    exec_token = _execution_id.set(exec_id)
    claim_token = _claim_id.set(claim_id)
    counter_token = _step_counter.set(itertools.count(0))
    try:
        yield exec_id
    finally:
        _step_counter.reset(counter_token)
        _claim_id.reset(claim_token)
        _execution_id.reset(exec_token)
