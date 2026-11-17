"""
The wire format the SDK sends. Kept intentionally identical to
collector/schema.py's TraceEvent — the two sides only agree on this JSON
shape, nothing else. A real package would publish this as a versioned
contract; for this project, keeping one copy on each side is enough.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

StepStatus = Literal["ok", "error"]


class TraceEvent(BaseModel):
    execution_id: str
    claim_id: str
    pipeline: str
    step: str
    step_index: int
    is_final_step: bool = False

    started_at: float
    ended_at: float

    status: StepStatus = "ok"
    error: Optional[str] = None

    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
