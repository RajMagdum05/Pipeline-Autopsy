import re
from typing import List

from .lineage import _depth, owning_stage
from .model import Observation, RANK, Stage
from .validators import VALIDATORS


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
                # Decision outcomes are context, not pipeline faults.
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

def _number(observations):
    for i, o in enumerate(observations, 1):
        o.id = f"obs_{i:03d}"
