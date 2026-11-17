"""
Pipeline Autopsy - reference implementation of the v2 diagnosis core.
Based on Project doc claude/reference/rca_reference.py (re-verified 16 Nov 2026).
Change vs original (16 Nov 2026): checks with check.kind == "decision_rule" are business
outcomes, recorded as info observations (family "decision"), never anomalies.
Change 2 (16 Nov 2026): rule R4 generalised from "no inputs recorded" to "starved": a failed stage
missing the output of a stopped upstream is propagated (strong), even if it has other inputs.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

INFRA = "infra"
DATA = "data"
RANK = {"info": 0, "pass": 0, "warn": 1, "fail": 2}


def artifact_id(content: Any, kind: str, execution_id: str) -> str:
    raw = content if isinstance(content, bytes) else json.dumps(content, sort_keys=True).encode()
    h = hashlib.sha256(execution_id.encode() + b"\x00" + kind.encode() + b"\x00" + raw)
    return "art_" + h.hexdigest()[:16]


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


REQUIRED_ALL = ["pipeline.name", "pipeline.version", "execution.id", "execution.entity_id", "autopsy.role"]
REQUIRED_STAGE = ["stage.name", "stage.status", "stage.attempt", "input.artifact_ids", "output.artifact_ids"]
VALID_STATUS = {"success", "failed", "partial", "skipped"}


def validate_trace(spans, manifest):
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


def build_stages(spans, manifest, artifacts):
    obs: List[Observation] = []
    stages = {st["name"]: Stage(st["name"]) for st in manifest["stages"]}
    by_name: Dict[str, list] = {}
    for s in spans:
        if s["attrs"].get("autopsy.role") == "stage" and s["attrs"].get("stage.name") in stages:
            by_name.setdefault(s["attrs"]["stage.name"], []).append(s)
    producer: Dict[str, str] = {}
    complete = True
    for name, group in by_name.items():
        group.sort(key=lambda s: (s["attrs"].get("stage.attempt", 1), s.get("start", 0)))
        final = group[-1]
        st = stages[name]
        st.executed, st.span_id, st.attempts = True, final["span_id"], len(group)
        st.status = final["attrs"].get("stage.status")
        st.inputs = list(final["attrs"].get("input.artifact_ids") or [])
        st.outputs = list(final["attrs"].get("output.artifact_ids") or [])
        for aid in st.outputs:
            producer[aid] = name
    for st_def in manifest["stages"]:
        st = stages[st_def["name"]]
        if not st.executed:
            continue
        for aid in st.inputs + st.outputs:
            if aid not in artifacts:
                obs.append(Observation("structural", "artifact_not_found", "warn", st.name,
                                       f"artifact {aid} referenced but not in store", span_id=st.span_id,
                                       artifact_id=aid))
                st.lineage_ok = False
        for kind in st_def.get("consumes", []):
            if kind in manifest.get("external_inputs", []):
                continue
            have = [a for a in st.inputs if artifacts.get(a, {}).get("kind") == kind]
            if not have:
                up = _producer_stage_of_kind(manifest, kind)
                if up and stages[up].executed and stages[up].outputs:
                    obs.append(Observation("structural", "lineage_gap", "warn", st.name,
                                           f"no input artifact of kind {kind!r} recorded", span_id=st.span_id))
                    st.lineage_ok = False
        if not st.lineage_ok:
            complete = False
    return stages, producer, obs, complete


def _producer_stage_of_kind(manifest, kind):
    for st in manifest["stages"]:
        if kind in st.get("produces", []):
            return st["name"]
    return None


def upstream_stages(manifest, name):
    st = next(s for s in manifest["stages"] if s["name"] == name)
    ups = [_producer_stage_of_kind(manifest, k) for k in st.get("consumes", [])]
    return [u for u in ups if u]


def owning_stage(span, by_id):
    cur = span
    while cur:
        if cur["attrs"].get("autopsy.role") == "stage":
            return cur
        cur = by_id.get(cur.get("parent"))
    return None


def detect_execution(spans, stages):
    out: List[Observation] = []
    by_id = {s["span_id"]: s for s in spans}
    for name, st in stages.items():
        if not st.executed:
            continue
        final = by_id[st.span_id]
        a = final["attrs"]
        if st.attempts > 1:
            out.append(Observation("execution", "retried", "info", name, f"{st.attempts} attempts",
                                   span_id=st.span_id))
        ops = [s for s in spans if s.get("status") == "ERROR" and s is not final
               and (owning_stage(s, by_id) or {}).get("span_id") == st.span_id]
        deepest = max(ops, key=lambda s: _depth(s, by_id), default=None)
        if st.status == "failed":
            src = deepest or final
            cls = src["attrs"].get("error.class") or a.get("error.class")
            out.append(Observation("execution", "stage_failed", "fail", name,
                                   f"{src['attrs'].get('error.type', 'Error')}: {src['attrs'].get('error.message', '')}",
                                   span_id=src["span_id"], error_class=cls))
        elif st.status == "partial":
            out.append(Observation("execution", "stage_partial", "warn", name, "stage reported partial",
                                   span_id=st.span_id))
        elif st.status == "success" and final.get("status") == "ERROR":
            out.append(Observation("structural", "status_mismatch", "warn", name,
                                   "span status ERROR but stage.status=success", span_id=st.span_id))
        elif deepest is not None:
            out.append(Observation("execution", "handled_operation_error", "info", name,
                                   f"operation {deepest['name']} errored but stage succeeded",
                                   span_id=deepest["span_id"]))
    return out


def _depth(span, by_id):
    d, cur = 0, span
    while cur and cur.get("parent"):
        d += 1
        cur = by_id.get(cur["parent"])
    return d


def detect_checks(spans, stages, producer):
    out: List[Observation] = []
    by_id = {s["span_id"]: s for s in spans}
    final_ids = {st.span_id for st in stages.values() if st.executed}
    for s in spans:
        own = owning_stage(s, by_id)
        if not own or own["span_id"] not in final_ids:
            continue
        for ev in s.get("events", []):
            if ev.get("name") != "autopsy.check":
                continue
            e = ev["attrs"]
            res = e.get("check.result")
            target = e.get("check.target_artifact_id")
            reporter = own["attrs"]["stage.name"]
            if e.get("check.kind") == "decision_rule":
                # Business-rule outcomes (e.g. claim not covered) are NOT pipeline faults.
                # Keep them as context (info) so explanations can cite them; never anomalous.
                if res in ("fail", "warn"):
                    out.append(Observation("decision", e["check.id"], "info", reporter,
                                           f"business rule {res}; observed={e.get('check.observed')!r}",
                                           span_id=s["span_id"], artifact_id=target, field=e.get("check.field"),
                                           reported_by=reporter))
                continue
            if res not in ("fail", "warn"):
                continue
            about = producer.get(target, reporter) if target else reporter
            out.append(Observation("check", e["check.id"], res, about,
                                   f"observed={e.get('check.observed')!r} expected={e.get('check.expected')!r}",
                                   span_id=s["span_id"], artifact_id=target, field=e.get("check.field"),
                                   reported_by=reporter))
    return out


def detect_contract(stages, artifacts, manifest):
    import jsonschema
    out: List[Observation] = []
    for name, st in stages.items():
        for aid in st.outputs:
            art = artifacts.get(aid)
            spec = manifest.get("artifacts", {}).get((art or {}).get("kind"), {})
            if not art or "schema" not in spec:
                continue
            for err in jsonschema.Draft202012Validator(spec["schema"]).iter_errors(art["content"]):
                fld = str(err.path[0]) if err.path else (
                    re.findall(r"'(.+?)' is a required", err.message) or [None])[0]
                out.append(Observation("contract", f"schema.{err.validator}", "fail", name, err.message[:160],
                                       span_id=st.span_id, artifact_id=aid, field=fld))
    return out


def v_grounded_fields(content, source, rule):
    text = json.dumps(source, ensure_ascii=False) if not isinstance(source, str) else source
    res = []
    for f in rule["fields"]:
        if f not in content or content[f] in (None, ""):
            continue
        res.append((f, str(content[f]) in text, f"value {content[f]!r}"))
    return res


def v_equals_upstream(content, source, rule):
    res = []
    for f in rule["fields"]:
        if f in content and f in source:
            res.append((f, content[f] == source[f], f"{content[f]!r} vs upstream {source[f]!r}"))
    return res


VALIDATORS: Dict[str, Callable] = {"grounded_fields": v_grounded_fields, "equals_upstream": v_equals_upstream}


def detect_consistency(stages, artifacts, manifest):
    out: List[Observation] = []
    for name, st in stages.items():
        for aid in st.outputs:
            art = artifacts.get(aid)
            for rule in manifest.get("artifacts", {}).get((art or {}).get("kind"), {}).get("consistency", []):
                srcs = [i for i in st.inputs if artifacts.get(i, {}).get("kind") == rule["source"]]
                if not srcs:
                    continue
                merged = [artifacts[i]["content"] for i in srcs]
                source = merged[0] if len(merged) == 1 else merged
                for fld, ok, detail in VALIDATORS[rule["validator"]](art["content"], source, rule):
                    out.append(Observation("consistency", rule["id"], "pass" if ok else "fail", name,
                                           detail + (" found in source" if ok else " NOT supported by source"),
                                           span_id=st.span_id, artifact_id=aid, field=fld,
                                           source_artifact_id=srcs[0]))
    return out


def trace_back(observations, producer):
    derived: List[Observation] = []
    work = [o for o in observations if o.anomalous and o.family in ("contract", "check") and o.field]
    seen = set()
    while work:
        o = work.pop()
        for g in observations:
            if (g.family == "consistency" and g.result == "pass" and g.artifact_id == o.artifact_id
                    and g.field == o.field and g.source_artifact_id):
                key = (g.source_artifact_id, o.field)
                if key in seen:
                    continue
                seen.add(key)
                d = Observation("derived", "bad_value_traced_to_input", "fail",
                                producer.get(g.source_artifact_id),
                                f"bad field {o.field!r} of {o.artifact_id} is present verbatim in {g.source_artifact_id}",
                                artifact_id=g.source_artifact_id, field=o.field)
                derived.append(d)
                work.append(d)
    return derived


def rca(manifest, stages, observations, grade):
    order = [s["name"] for s in manifest["stages"]]
    anomalies: Dict[str, List[Observation]] = {n: [] for n in order}
    for o in observations:
        if o.anomalous and o.stage in anomalies and o.family != "structural":
            anomalies[o.stage].append(o)
    implicated: Dict[str, str] = {}
    for o in observations:
        if o.anomalous and o.artifact_id and o.family in ("check", "contract", "consistency", "derived"):
            if RANK[o.result] > RANK.get(implicated.get(o.artifact_id, "info"), 0):
                implicated[o.artifact_id] = o.result
    tainted: set = set()
    findings: List[dict] = []
    role: Dict[str, str] = {}

    def add(stage, r, cls, conf, link=None, caused_by=None, note=None):
        role[stage] = r
        ev = [o.id for o in anomalies[stage]]
        sev = max([o.result for o in anomalies[stage]], key=lambda x: RANK[x], default="info")
        findings.append({"stage": stage, "role": r, "classification": cls, "confidence": conf, "severity": sev,
                         "link": link, "caused_by": sorted(set(caused_by or [])), "evidence": ev, "note": note})

    def cap(conf):
        if grade == "B" and conf == "supported":
            return "possible"
        return conf

    for name in order:
        st = stages[name]
        ups = upstream_stages(manifest, name)
        bad_ups = [u for u in ups if role.get(u) in ("origin", "propagated", "not_executed")]
        stopped_ups = [u for u in ups if role.get(u) == "not_executed"
                       or (role.get(u) in ("origin", "propagated") and stages[u].status == "failed")]
        if not st.executed:
            if stopped_ups:
                add(name, "not_executed", "DOWNSTREAM_PROPAGATED_SUSPICION", cap("supported"), "strong", stopped_ups)
            else:
                role[name] = "missing"
            continue
        obs = anomalies[name]
        starved = [u for u in stopped_ups if not set(stages[u].outputs) & set(st.inputs)]
        bad_in = [a for a in st.inputs if a in implicated or a in tainted]
        strong_in = [a for a in bad_in if implicated.get(a) == "fail" or a in tainted]
        if obs:
            infra = any(o.family == "execution" and o.error_class == INFRA for o in obs)
            invented = any(o.family == "consistency" and o.result == "fail" for o in obs)
            direct = [o for o in obs if o.family != "derived"]
            if infra or invented:
                cls = "SERVICE_EXECUTION_FAILURE" if infra else "SOURCE_EVIDENCE_CONTRADICTION"
                add(name, "origin", cls, cap("supported"))
            elif bad_in:
                srcs = [o.stage for o in observations if o.artifact_id in bad_in and o.anomalous and o.stage]
                srcs += [u for u in ups if role.get(u) in ("propagated", "tainted", "origin")]
                unclassified = any(o.family == "execution" and o.result == "fail"
                                   and o.error_class not in (INFRA, DATA) for o in obs)
                add(name, "propagated", "INVALID_UPSTREAM_INPUT",
                    cap("supported" if strong_in and not unclassified else "possible"),
                    "strong" if strong_in else "weak", [s for s in srcs if s != name],
                    note="error.class missing: cannot rule out an independent failure" if unclassified else None)
            elif starved:
                # S failed and is missing the output of a stopped upstream (failed / not executed).
                # Generalises the original "no inputs at all" rule to partial starvation, e.g. a
                # claim-level stage that got the policy facts but not the blocked bill's facts.
                add(name, "propagated", "DOWNSTREAM_PROPAGATED_SUSPICION", cap("supported"), "strong", starved)
            elif bad_ups:
                add(name, "propagated", "DOWNSTREAM_PROPAGATED_SUSPICION", "possible", "weak", bad_ups,
                    note="upstream is anomalous but no implicated artifact links it to this stage")
            else:
                has_artifact_fail = any(o.family in ("contract", "check") for o in direct)
                exec_fail = [o for o in direct if o.family == "execution" and o.result == "fail"]
                if has_artifact_fail:
                    add(name, "origin", "OUTPUT_CONTRACT_VIOLATION", cap("supported"))
                elif not direct:
                    add(name, "origin", "OUTPUT_CONTRACT_VIOLATION", "possible",
                        note="evidence is derived only: the bad value is in this stage's output, "
                             "but no check on this stage flagged it. The source input itself may be wrong.")
                elif exec_fail and exec_fail[0].error_class == DATA:
                    add(name, "origin", "INVALID_UPSTREAM_INPUT", "possible",
                        note="stage rejected its input but no check flags that input. Coverage gap: add a check upstream.")
                else:
                    add(name, "origin", "SERVICE_EXECUTION_FAILURE", cap("supported"))
            tainted.update(a for a in st.outputs if a not in implicated)
        elif bad_in:
            srcs = [o.stage for o in observations if o.artifact_id in bad_in and o.anomalous and o.stage]
            srcs += [u for u in ups if role.get(u) in ("propagated", "tainted")]
            add(name, "tainted", "DOWNSTREAM_PROPAGATED_SUSPICION",
                cap("supported" if strong_in else "possible"), "strong" if strong_in else "weak", srcs)
            tainted.update(st.outputs)
        else:
            role[name] = "healthy"

    origins = [f for f in findings if f["role"] == "origin"]
    if grade == "C":
        verdict = "INSUFFICIENT_EVIDENCE"
    elif not findings:
        verdict = "NO_ISSUE_DETECTED"
    elif len(origins) == 1:
        verdict = "ROOT_CAUSE_IDENTIFIED"
    elif len(origins) > 1:
        verdict = "MULTIPLE_ROOT_CAUSES"
    else:
        verdict = "INSUFFICIENT_EVIDENCE"
    return {"verdict": verdict, "findings": findings, "roles": role}


def diagnose(spans, artifacts, manifest):
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
    result = rca(manifest, stages, observations, grade)
    if any(r == "missing" for r in result["roles"].values()) and grade == "A":
        grade = "B"
        for f in result["findings"]:
            if f["confidence"] == "supported":
                f["confidence"] = "possible"
    result["trace_grade"] = grade
    result["observations"] = observations
    return result


def _number(observations):
    for i, o in enumerate(observations, 1):
        o.id = f"obs_{i:03d}"
