from typing import Dict, List

from .lineage import upstream_stages
from .model import DATA, INFRA, Observation, RANK


def rca(manifest, stages, observations, grade, upstream_resolver=None):
    upstream_resolver = upstream_resolver or upstream_stages
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
        ups = upstream_resolver(manifest, name)
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
                # a run-level stage that received some inputs but missed another stopped input.
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
