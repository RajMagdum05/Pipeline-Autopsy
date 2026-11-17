"""Fan-out extension prototype for the reference diagnosis core.

Problem: insurance-pipeline-new processes N documents per claim run. The same stage
(document_processing, information_extraction, ...) runs once PER DOCUMENT, and a
claim-level stage (adjudication) consumes the outputs of all of them. A policy
document must pass its gates before any proof starts (control dependency).

Approach (no change to the RCA rules themselves):
  1. Manifest stages declare scope: "item" (once per document) or "run" (once per run),
     and optional `requires` control edges: [{stage, item_role}].
  2. Stage spans carry pipeline.stage.item_id and pipeline.stage.item_role.
  3. expand() rewrites manifest, spans and artifact kinds so every item-scoped stage
     instance becomes its own stage "name@item". Kinds become "kind@item".
     Run-scoped stages consume every item-qualified instance of their kinds.
     Control edges become a synthetic consumed kind "gate@item" (no artifact):
     upstream_stages() then sees the dependency, so a blocked proof is explained
     as not_executed caused by the failed policy stage.
  4. The unchanged reference rca() runs on the expanded inputs.
"""
from __future__ import annotations

import copy
from typing import Dict, List

import rca_reference as core

ITEM = "pipeline.stage.item_id"
ROLE = "pipeline.stage.item_role"


def _multi_producer_upstream(manifest, name):
    st = next(s for s in manifest["stages"] if s["name"] == name)
    ups = []
    for k in st.get("consumes", []):
        for s in manifest["stages"]:
            if k in s.get("produces", []) and s["name"] not in ups:
                ups.append(s["name"])
    return ups


def _topo_sort(stages):
    """Stable Kahn sort: RCA walks stages in dependency order, and control edges
    (policy gate -> proofs) cut across the per-stage expansion order."""
    producer = {k: st["name"] for st in stages for k in st["produces"]}
    deps = {st["name"]: {producer[k] for k in st["consumes"] if k in producer and producer[k] != st["name"]}
            for st in stages}
    out, done = [], set()
    while len(out) < len(stages):
        ready = [st for st in stages if st["name"] not in done and deps[st["name"]] <= done]
        if not ready:
            raise ValueError("cycle in expanded manifest")
        out.append(ready[0])
        done.add(ready[0]["name"])
    return out


def expand(spans, artifacts, manifest, items: Dict[str, str]):
    """items: {item_id: item_role}. In production this comes from the run span's
    pipeline.run.items attribute or is derived from stage spans."""
    m2 = {k: v for k, v in manifest.items() if k not in ("stages", "artifacts")}
    m2["artifacts"] = {}
    stages_out: List[dict] = []
    item_ids = list(items)
    for st in manifest["stages"]:
        if st.get("scope", "run") == "item":
            for it in item_ids:
                if st.get("item_roles") and items[it] not in st["item_roles"]:
                    continue
                consumes = [f"{k}@{it}" if k not in manifest.get("external_inputs", []) else k
                            for k in st.get("consumes", [])]
                for req in st.get("requires", []):
                    for gate_item, r in items.items():
                        if r == req["item_role"] and gate_item != it:
                            consumes.append(f"gate:{req['stage']}@{gate_item}")
                produces = [f"{k}@{it}" for k in st.get("produces", [])]
                produces.append(f"gate:{st['name']}@{it}")
                stages_out.append({"name": f"{st['name']}@{it}", "consumes": consumes, "produces": produces})
                for k in st.get("produces", []):
                    spec = copy.deepcopy(manifest.get("artifacts", {}).get(k))
                    if spec:
                        for rule in spec.get("consistency", []):
                            rule["source"] = f"{rule['source']}@{it}"
                        m2["artifacts"][f"{k}@{it}"] = spec
        else:
            consumes = []
            for k in st.get("consumes", []):
                producer = next((s for s in manifest["stages"] if k in s.get("produces", [])), None)
                if producer and producer.get("scope") == "item":
                    consumes += [f"{k}@{it}" for it in item_ids
                                 if not producer.get("item_roles") or items[it] in producer["item_roles"]]
                else:
                    consumes.append(k)
            stages_out.append({"name": st["name"], "consumes": consumes, "produces": list(st.get("produces", []))})
            for k in st.get("produces", []):
                if k in manifest.get("artifacts", {}):
                    m2["artifacts"][k] = copy.deepcopy(manifest["artifacts"][k])
    m2["stages"] = _topo_sort(stages_out)
    gate_kinds = sorted({k for st in stages_out for k in st["consumes"] + st["produces"] if k.startswith("gate:")})
    # gates are control dependencies with no artifact: exclude them from lineage-gap checks
    m2["external_inputs"] = list(manifest.get("external_inputs", [])) + gate_kinds

    s2 = copy.deepcopy(spans)
    producer_item: Dict[str, str] = {}
    for s in s2:
        a = s["attrs"]
        if a.get("autopsy.role") == "stage" and a.get(ITEM):
            a["stage.name"] = f"{a['stage.name']}@{a[ITEM]}"
            for aid in a.get("output.artifact_ids") or []:
                producer_item[aid] = a[ITEM]
    a2 = {}
    for aid, art in artifacts.items():
        it = producer_item.get(aid)
        a2[aid] = {**art, "kind": f"{art['kind']}@{it}" if it else art["kind"]}
    return s2, a2, m2


def diagnose(spans, artifacts, manifest, items):
    s2, a2, m2 = expand(spans, artifacts, manifest, items)
    original = core.upstream_stages
    core.upstream_stages = _multi_producer_upstream
    try:
        return core.diagnose(s2, a2, m2)
    finally:
        core.upstream_stages = original
