"""
Trace schema — Stage 1 of the build order.

This is the one data shape the SDK (running inside the enterprise pipeline)
and the Collector (running inside Pipeline Autopsy) both agree on. Nothing
else needs to be shared between them.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

StepStatus = Literal["ok", "error"]


class TraceEvent(BaseModel):
    """One pipeline step, as reported by the SDK after it ran."""

    execution_id: str = Field(..., description="Groups every step of one pipeline run")
    claim_id: str = Field(..., description="The business object this run was processing")
    pipeline: str = Field(..., description="Which monitored pipeline this came from")
    step: str = Field(..., description="Step name, e.g. 'ocr', 'extraction', 'rag'")
    step_index: int = Field(..., description="Position of this step in the pipeline, 0-based")
    is_final_step: bool = Field(False, description="True on the last step — triggers diagnosis")

    started_at: float = Field(..., description="Unix timestamp, seconds")
    ended_at: float = Field(..., description="Unix timestamp, seconds")

    status: StepStatus = "ok"
    error: Optional[str] = None

    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)

    @property
    def latency_ms(self) -> float:
        return round((self.ended_at - self.started_at) * 1000, 1)


class EvidenceItem(BaseModel):
    label: str
    expected: str
    actual: str


class Diagnosis(BaseModel):
    """What the Root Cause + Evidence engines produce for one execution."""

    execution_id: str
    status: Literal["healthy", "suspicious", "root_cause_found"]
    root_cause_step: Optional[str] = None
    confidence: Optional[float] = None
    rule: Optional[str] = Field(None, description="Which triage rule fired")
    evidence: list[EvidenceItem] = Field(default_factory=list)
    propagated_to: list[str] = Field(default_factory=list)
    computed_at: float
