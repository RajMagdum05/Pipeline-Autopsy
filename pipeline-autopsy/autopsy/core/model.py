from dataclasses import dataclass, field
from typing import List, Optional


INFRA = "infra"

DATA = "data"

RANK = {"info": 0, "pass": 0, "warn": 1, "fail": 2}

@dataclass
class Observation:
    family: str
    code: str
    result: str
    stage: Optional[str]
    detail: str
    span_id: Optional[str] = None
    artifact_id: Optional[str] = None
    field: Optional[str] = None
    reported_by: Optional[str] = None
    error_class: Optional[str] = None
    source_artifact_id: Optional[str] = None
    id: str = ""

    @property
    def anomalous(self) -> bool:
        return self.result in ("warn", "fail")

@dataclass
class Stage:
    name: str
    executed: bool = False
    span_id: Optional[str] = None
    status: Optional[str] = None
    attempts: int = 0
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    lineage_ok: bool = True
