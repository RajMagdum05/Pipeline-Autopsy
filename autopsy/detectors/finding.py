from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


def _gen_uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class Finding:
    """
    Standardized internal finding structure for telemetry failure and anomaly candidates.
    """
    finding_type: str  # e.g., SPAN_ERROR_STATUS, EXCEPTION_EVENT, TIMEOUT_EXCEEDED, DEPENDENCY_FAILURE, STRUCTURAL_WARNING, EXPLICIT_VALIDATION_FAILURE
    execution_id: str
    trace_id: str
    service_name: str
    operation_name: str
    description: str
    evidence_type: str  # e.g., SPAN_STATUS, EXCEPTION_DATA, TIMEOUT_METRIC, DEPENDENCY_LINK, STRUCTURAL_WARNING, VALIDATION_EVENT
    detector_name: str
    span_id: Optional[str] = None
    severity: str = "ERROR"  # INFO, WARNING, ERROR, CRITICAL
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_data: Dict[str, Any] = field(default_factory=dict)
    finding_id: str = field(default_factory=_gen_uuid)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes Finding to dictionary format."""
        return {
            "finding_id": self.finding_id,
            "finding_type": self.finding_type,
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "service_name": self.service_name,
            "operation_name": self.operation_name,
            "severity": self.severity,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "description": self.description,
            "evidence_type": self.evidence_type,
            "evidence_data": self.evidence_data,
            "detector_name": self.detector_name,
        }
