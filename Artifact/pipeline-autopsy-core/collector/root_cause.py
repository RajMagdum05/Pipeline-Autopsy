"""
Root Cause Engine — Stage 6.

The core rule this project is built around: root cause is the first step
whose output stopped matching reality, not whichever step looks worst
downstream. This module doesn't decide *whether* something is wrong
(that's triage.py) — it decides *which one of the flagged steps came
first*, and labels everything after it as propagation rather than a
second, independent problem.
"""
from __future__ import annotations

import time

from . import storage
from .evidence import build_evidence
from .schema import Diagnosis
from .triage import STEP_RULES, check_step_errored


def diagnose(execution_id: str) -> Diagnosis:
    events = storage.get_trace_events(execution_id)
    events_by_step = {e["step"]: e for e in events}

    root_cause_step: str | None = None
    finding = None

    for event in events:  # already ordered by step_index
        step = event["step"]
        result = check_step_errored(events_by_step, step) or (
            STEP_RULES[step](events_by_step) if step in STEP_RULES else None
        )
        if result is not None:
            root_cause_step = step
            finding = result
            break  # first flagged step wins — stop looking

    if root_cause_step is None:
        diagnosis = Diagnosis(
            execution_id=execution_id,
            status="healthy",
            evidence=[],
            propagated_to=[],
            computed_at=time.time(),
        )
    else:
        propagated_to = [e["step"] for e in events if e["step_index"] > next(
            e2["step_index"] for e2 in events if e2["step"] == root_cause_step
        )]
        diagnosis = Diagnosis(
            execution_id=execution_id,
            status="root_cause_found",
            root_cause_step=root_cause_step,
            confidence=finding.confidence,
            rule=finding.rule,
            evidence=build_evidence(finding.rule, finding.raw),
            propagated_to=propagated_to,
            computed_at=time.time(),
        )

    storage.save_diagnosis(diagnosis)
    storage.update_execution_status(execution_id, diagnosis.status)
    return diagnosis
