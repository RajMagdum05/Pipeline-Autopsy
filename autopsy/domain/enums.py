from enum import Enum


class ExecutionStatus(str, Enum):
    """Execution lifecycle status of an observed workflow run."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELED = "CANCELED"


class SpanKind(str, Enum):
    """OpenTelemetry-aligned span kind classification."""
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class SpanStatusCode(str, Enum):
    """Status code indicating whether an operation succeeded or faulted."""
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class EvidenceType(str, Enum):
    """Classification of forensic evidence supporting an autopsy finding."""
    LOG_SNIPPET = "LOG_SNIPPET"
    PAYLOAD_REF = "PAYLOAD_REF"
    METRIC_ANOMALY = "METRIC_ANOMALY"
    EXCEPTION_STACK = "EXCEPTION_STACK"
    TRACE_DIFF = "TRACE_DIFF"
    METRIC_TIMESERIES = "METRIC_TIMESERIES"
    OTHER = "OTHER"


class FailureType(str, Enum):
    """Taxonomy of detected execution failures across software and AI pipelines."""
    EXCEPTION = "EXCEPTION"
    TIMEOUT = "TIMEOUT"
    DATA_CORRUPTION = "DATA_CORRUPTION"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    DEPENDENCY_OUTAGE = "DEPENDENCY_OUTAGE"
    HALLUCINATION = "HALLUCINATION"
    RATE_LIMIT = "RATE_LIMIT"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    CUSTOM = "CUSTOM"


class SeverityLevel(str, Enum):
    """Severity classification for failures and incidents."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    """Lifecycle state of an investigated Autopsy incident."""
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
