from .contract import validate_trace
from .detectors import (
    _number, detect_checks, detect_consistency, detect_contract, detect_execution,
)
from .lineage import build_stages
from .rca import rca
from .lineage import trace_back
from .normalize import normalize


def diagnose(spans, artifacts, manifest, items=None):
    spans = normalize(spans)
    upstream_resolver = None
    if items is not None:
        from .fanout import _multi_producer_upstream, expand

        spans, artifacts, manifest = expand(spans, artifacts, manifest, items)
        upstream_resolver = _multi_producer_upstream
    grade, structural = validate_trace(spans, manifest)
    if grade == "C":
        _number(structural)
        return {"verdict": "INSUFFICIENT_EVIDENCE", "trace_grade": "C", "findings": [], "roles": {},
                "observations": structural}
    stages, producer, s_obs, complete = build_stages(spans, manifest, artifacts)
    if not complete and grade == "A":
        grade = "B"
    observations = structural + s_obs
    observations += detect_execution(spans, stages)
    observations += detect_checks(spans, stages, producer)
    observations += detect_contract(stages, artifacts, manifest)
    observations += detect_consistency(stages, artifacts, manifest)
    observations += trace_back(observations, producer)
    if any(o.code == "status_mismatch" for o in observations) and grade == "A":
        grade = "B"
    _number(observations)
    result = rca(manifest, stages, observations, grade, upstream_resolver=upstream_resolver)
    if any(r == "missing" for r in result["roles"].values()) and grade == "A":
        grade = "B"
        for f in result["findings"]:
            if f["confidence"] == "supported":
                f["confidence"] = "possible"
    result["trace_grade"] = grade
    result["observations"] = observations
    return result
