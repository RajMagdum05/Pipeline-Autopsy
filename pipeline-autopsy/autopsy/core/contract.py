import hashlib
import json
from typing import Any, List

from .model import Observation


def artifact_id(content: Any, kind: str, run_id: str, item_id: str = "") -> str:
    if isinstance(content, bytes):
        raw = content
    elif isinstance(content, str):
        raw = content.encode("utf-8")
    else:
        raw = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    h = hashlib.sha256(run_id.encode() + b"\x00" + kind.encode() + b"\x00" + item_id.encode()
                       + b"\x00" + raw)
    return "art_" + h.hexdigest()[:16]

REQUIRED_ALL = ["pipeline.name", "pipeline.version", "execution.id", "autopsy.role"]

REQUIRED_STAGE = ["stage.name", "stage.status", "stage.attempt", "input.artifact_ids", "output.artifact_ids"]

VALID_STATUS = {"success", "failed", "partial", "skipped"}

def validate_trace(spans, manifest):
    # ``diagnose`` normalizes first; this validator consumes that internal shape.
    obs: List[Observation] = []
    grade = "A"

    def lower(to):
        nonlocal grade
        if to > grade:
            grade = to

    ids = {s["span_id"] for s in spans}
    roots = [s for s in spans if s["attrs"].get("autopsy.role") == "execution"]
    if len(roots) != 1:
        obs.append(Observation("structural", "execution_span_count", "fail", None,
                               f"expected exactly 1 execution span, found {len(roots)}"))
        lower("C")
    item_scoped = {st["name"] for st in manifest.get("stages", []) if st.get("scope") == "item"}
    if item_scoped and roots and "pipeline.run.items" not in roots[0]["attrs"]:
        obs.append(Observation("structural", "missing_run_items", "warn", None,
                               "run span is missing pipeline.run.items", span_id=roots[0]["span_id"]))
        lower("B")
    for s in spans:
        a = s["attrs"]
        missing = [k for k in REQUIRED_ALL if k not in a]
        if missing:
            obs.append(Observation("structural", "missing_required_attribute", "fail", a.get("stage.name"),
                                   f"span {s['span_id']} missing {missing}", span_id=s["span_id"]))
            lower("C")
        if s.get("parent") and s["parent"] not in ids:
            obs.append(Observation("structural", "orphan_span", "warn", a.get("stage.name"),
                                   f"span {s['span_id']} parent {s['parent']} not in trace", span_id=s["span_id"]))
            lower("B")
        if a.get("autopsy.role") == "stage":
            miss = [k for k in REQUIRED_STAGE if k not in a]
            if a.get("stage.name") in item_scoped and "pipeline.stage.item_id" not in a:
                miss.append("pipeline.stage.item_id")
            if "stage.name" in miss or "stage.status" in miss:
                obs.append(Observation("structural", "missing_stage_identity", "fail", None,
                                       f"stage span {s['span_id']} missing {miss}", span_id=s["span_id"]))
                lower("C")
            elif miss:
                obs.append(Observation("structural", "missing_stage_attribute", "warn", a["stage.name"],
                                       f"stage span {s['span_id']} missing {miss}", span_id=s["span_id"]))
                lower("B")
            if a.get("stage.status") not in VALID_STATUS | {None}:
                obs.append(Observation("structural", "invalid_stage_status", "warn", a.get("stage.name"),
                                       f"stage.status={a.get('stage.status')!r}", span_id=s["span_id"]))
                lower("B")
            known = {st["name"] for st in manifest["stages"]}
            if a.get("stage.name") and a["stage.name"] not in known:
                obs.append(Observation("structural", "unknown_stage", "warn", a["stage.name"],
                                       "stage not declared in manifest", span_id=s["span_id"]))
                lower("B")
    parent = {s["span_id"]: s.get("parent") for s in spans}
    for sid in parent:
        seen, cur = set(), sid
        while cur:
            if cur in seen:
                obs.append(Observation("structural", "span_cycle", "fail", None, f"cycle through span {sid}"))
                lower("C")
                break
            seen.add(cur)
            cur = parent.get(cur)
    return grade, obs
