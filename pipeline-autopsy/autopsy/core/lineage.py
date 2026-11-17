from typing import Dict, List

from .model import Observation, Stage


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

def _depth(span, by_id):
    d, cur = 0, span
    while cur and cur.get("parent"):
        d += 1
        cur = by_id.get(cur["parent"])
    return d

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
