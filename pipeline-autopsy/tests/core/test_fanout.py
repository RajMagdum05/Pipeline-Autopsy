"""Golden cases for the fan-out extension, shaped like insurance-pipeline-new:
one policy document + N proof documents, policy gate before proofs, claim-level adjudication."""
import itertools

from autopsy.core import fanout as rca_fanout
from autopsy.core import artifact_id

MANIFEST = {
    "pipeline": "insurance-claims", "version": "2.0.0",
    "external_inputs": ["source_document", "claim_form"],
    "stages": [
        {"name": "document_processing", "scope": "item", "consumes": ["source_document"], "produces": ["page_text"]},
        {"name": "content_classification", "scope": "item", "consumes": ["page_text"], "produces": ["classification"]},
        {"name": "information_extraction", "scope": "item", "consumes": ["page_text", "classification"],
         "produces": ["document_facts"]},
        {"name": "extraction_validation", "scope": "item", "consumes": ["document_facts"], "produces": ["validated_facts"]},
        {"name": "adjudication", "scope": "run", "consumes": ["validated_facts", "claim_form"], "produces": ["decision"]},
        {"name": "final_result", "scope": "run", "consumes": ["decision"], "produces": ["claim_result"]},
    ],
    "artifacts": {
        "document_facts": {"consistency": [{"id": "extraction.grounded_in_page_text", "validator": "grounded_fields",
                                            "source": "page_text", "fields": ["admission_date", "total"]}]},
    },
}
# proofs may only start after the policy passed extraction_validation (control edge)
for st in MANIFEST["stages"]:
    if st["scope"] == "item" and st["name"] == "document_processing":
        st["requires"] = [{"stage": "extraction_validation", "item_role": "policy"}]

ITEMS = {"pol": "policy", "bill": "proof", "disch": "proof"}


class Run:
    def __init__(self):
        self.spans, self.store, self.n = [], {}, itertools.count(1)
        self.base = {"pipeline.name": "insurance-claims", "pipeline.version": "2.0.0",
                     "pipeline.run.id": "run_1", "pipeline.entity.id": "claim_1"}
        self.root = self._span("claim_run", None, {"pipeline.span.role": "execution",
                                                     "pipeline.run.items": [f"{item}:{role}" for item, role in ITEMS.items()]})

    def _span(self, name, parent, attrs, status="OK", events=None):
        s = {"span_id": f"s{next(self.n)}", "parent": parent, "name": name, "status": status,
             "attrs": {**self.base, **attrs}, "events": events or [], "start": len(self.spans)}
        self.spans.append(s)
        return s

    def put(self, kind, content, item):
        aid = artifact_id({"item": item, "c": content}, kind, "run_1", item_id=item or "")
        self.store[aid] = {"kind": kind, "content": content}
        return aid

    def stage(self, name, item, inputs, outputs=(), status="success", err=None, checks=()):
        attrs = {"pipeline.span.role": "stage", "pipeline.stage.name": name, "pipeline.stage.status": status, "pipeline.stage.attempt": 1,
                 "pipeline.artifact.input_ids": list(inputs), "pipeline.artifact.output_ids": list(outputs)}
        if item:
            attrs.update({rca_fanout.ITEM: item, rca_fanout.ROLE: ITEMS[item]})
        if err:
            attrs.update({"error.type": err[0], "error.message": err[1], "pipeline.error.class": err[2]})
        events = [{"name": "pipeline.check", "attrs": c} for c in checks]
        return self._span(name, self.root["span_id"], attrs, "ERROR" if status == "failed" else "OK", events)

    def doc(self, item, text="Admission 2025-03-02. Total 1200 INR.", facts=None, ocr_check=None):
        src = self.put("source_document", {"sha256": item}, item)
        pt = self.put("page_text", {"text": text}, item)
        chk = [{"pipeline.check.id": "ocr.quality", "pipeline.check.kind": "threshold", "pipeline.check.result": ocr_check,
                "pipeline.check.target_artifact_id": pt, "pipeline.check.action": "continued"}] if ocr_check else []
        self.stage("document_processing", item, [src], [pt], checks=chk)
        cl = self.put("classification", {"type": "x"}, item)
        self.stage("content_classification", item, [pt], [cl])
        facts = facts or {"admission_date": "2025-03-02", "total": "1200"}
        df = self.put("document_facts", facts, item)
        self.stage("information_extraction", item, [pt, cl], [df])
        vf = self.put("validated_facts", facts, item)
        self.stage("extraction_validation", item, [df], [vf])
        return vf

    def claim_level(self, facts_ids, status="success", err=None):
        form = self.put("claim_form", {"amount": 1200}, None)
        if status == "success":
            d = self.put("decision", {"decision": "approve"}, None)
            self.stage("adjudication", None, facts_ids + [form], [d])
            c = self.put("claim_result", {"decision": "approve"}, None)
            self.stage("final_result", None, [d], [c])
        else:
            self.stage("adjudication", None, facts_ids + [form], [], status="failed", err=err)

    def result(self, items=ITEMS):
        return rca_fanout.diagnose(self.spans, self.store, MANIFEST, items)


def origins(res):
    return sorted(f["stage"] for f in res["findings"] if f["role"] == "origin")


def by_stage(res):
    return {f["stage"]: f for f in res["findings"]}


def test_f1_healthy_multi_document_run():
    r = Run()
    ids = [r.doc("pol"), r.doc("bill"), r.doc("disch")]
    r.claim_level(ids)
    res = r.result()
    assert res["verdict"] == "NO_ISSUE_DETECTED", res["findings"]
    assert res["trace_grade"] == "A", [o.detail for o in res["observations"] if o.family == "structural"]


def test_f2_one_proof_bad_ocr_isolated_to_that_document():
    r = Run()
    bad = "Admission 2024-03-02. Total 1200 INR."          # OCR misread the year
    ids = [r.doc("pol"), r.doc("bill", text=bad, facts={"admission_date": "2024-03-02", "total": "1200"},
                                ocr_check="warn"), r.doc("disch")]
    r.claim_level(ids, status="failed", err=("CoverageRuleFailed", "admission before coverage start", "data"))
    res = r.result()
    f = by_stage(res)
    assert origins(res) == ["document_processing@bill"], res["findings"]
    assert f["adjudication"]["role"] == "propagated"
    assert f["adjudication"]["caused_by"] and all("disch" not in c for c in f["adjudication"]["caused_by"])
    assert not any(k.endswith("@disch") or k.endswith("@pol") for k in f if f[k]["role"] != "not_executed")


def test_f3_policy_gate_failure_blocks_proofs_as_impact():
    r = Run()
    src = r.put("source_document", {"sha256": "pol"}, "pol")
    pt = r.put("page_text", {"text": "unreadable"}, "pol")
    r.stage("document_processing", "pol", [src], [pt], status="failed",
            err=("OCRQualityGateFailed", "policy text below quality threshold", "data"),
            checks=[{"pipeline.check.id": "ocr.quality", "pipeline.check.kind": "threshold", "pipeline.check.result": "fail",
                     "pipeline.check.target_artifact_id": pt, "pipeline.check.action": "blocked"}])
    res = r.result()
    f = by_stage(res)
    assert origins(res) == ["document_processing@pol"], res["findings"]
    for item in ("bill", "disch"):
        assert f[f"document_processing@{item}"]["role"] == "not_executed"
    assert f["adjudication"]["role"] == "not_executed"


def test_f4_llm_outage_on_one_proof_is_service_failure():
    r = Run()
    ids = [r.doc("pol")]
    src = r.put("source_document", {"sha256": "bill"}, "bill")
    pt = r.put("page_text", {"text": "Admission 2025-03-02. Total 1200 INR."}, "bill")
    r.stage("document_processing", "bill", [src], [pt])
    r.stage("content_classification", "bill", [pt], [], status="failed",
            err=("ServiceUnavailable", "503 from model API", "infra"))
    ids.append(r.doc("disch"))
    r.claim_level(ids, status="failed", err=("MissingProof", "hospital bill facts unavailable", "data"))
    res = r.result()
    f = by_stage(res)
    assert "content_classification@bill" in origins(res)
    assert f["content_classification@bill"]["classification"] == "SERVICE_EXECUTION_FAILURE"
    assert f["information_extraction@bill"]["role"] == "not_executed"


def test_f5_extraction_invents_value_on_one_proof():
    r = Run()
    ids = [r.doc("pol"), r.doc("bill", facts={"admission_date": "2025-03-02", "total": "9999"}), r.doc("disch")]
    r.claim_level(ids, status="failed", err=("AmountRuleFailed", "bill total exceeds claimed amount", "data"))
    res = r.result()
    f = by_stage(res)
    assert origins(res) == ["information_extraction@bill"], res["findings"]
    assert f["information_extraction@bill"]["classification"] == "SOURCE_EVIDENCE_CONTRADICTION"
    assert f["adjudication"]["role"] == "propagated"


def _rule(rule_id, target, field, result="fail"):
    return {"pipeline.check.id": rule_id, "pipeline.check.kind": "decision_rule", "pipeline.check.result": result,
            "pipeline.check.target_artifact_id": target, "pipeline.check.field": field, "pipeline.check.action": "continued"}


def _adjudicate(r, ids, rule_checks, decision="REJECTED"):
    form = r.put("claim_form", {"amount": 1200}, None)
    d = r.put("decision", {"decision": decision}, None)
    r.stage("adjudication", None, ids + [form], [d], checks=rule_checks)
    c = r.put("claim_result", {"decision": decision}, None)
    r.stage("final_result", None, [d], [c])


def test_f6_clean_rejection_is_not_a_pipeline_fault():
    """Genuinely uncovered claim: correct OCR, correct extraction, rule fails -> no finding."""
    r = Run()
    text = "Admission 2024-03-02. Total 1200 INR."          # really outside coverage
    ids = [r.doc("pol"), r.doc("bill", text=text, facts={"admission_date": "2024-03-02", "total": "1200"}),
           r.doc("disch")]
    _adjudicate(r, ids, [_rule("rule.service_in_coverage", ids[1], "admission_date")])
    res = r.result()
    assert res["verdict"] == "NO_ISSUE_DETECTED", res["findings"]
    assert any(o.family == "decision" and o.result == "info" for o in res["observations"])


def test_f7_rejection_caused_by_ocr_misread_is_traced_to_ocr():
    """Same rejection, but the OCR misread the year (quality check warned) -> origin is bill OCR."""
    r = Run()
    bad = "Admission 2024-03-02. Total 1200 INR."
    ids = [r.doc("pol"), r.doc("bill", text=bad, facts={"admission_date": "2024-03-02", "total": "1200"},
                                ocr_check="warn"), r.doc("disch")]
    _adjudicate(r, ids, [_rule("rule.service_in_coverage", ids[1], "admission_date")])
    res = r.result()
    f = by_stage(res)
    assert origins(res) == ["document_processing@bill"], res["findings"]
    assert f["adjudication"]["role"] == "tainted" and f["final_result"]["role"] == "tainted"
    assert not any("@pol" in k or "@disch" in k for k in f)


def test_f8_claim_stage_starved_by_failed_proof_is_strong_propagation():
    """Adjudication has the policy facts but not the bill's (bill classification hit a 503)."""
    r = Run()
    ids = [r.doc("pol")]
    src = r.put("source_document", {"sha256": "bill"}, "bill")
    pt = r.put("page_text", {"text": "Admission 2025-03-02. Total 1200 INR."}, "bill")
    r.stage("document_processing", "bill", [src], [pt])
    r.stage("content_classification", "bill", [pt], [], status="failed",
            err=("ServiceUnavailable", "503 from model API", "infra"))
    ids.append(r.doc("disch"))
    r.claim_level(ids, status="failed", err=("AdjudicationInputMissing", "no accepted financial proof", "data"))
    f = by_stage(r.result())
    assert f["adjudication"]["role"] == "propagated"
    assert f["adjudication"]["link"] == "strong" and f["adjudication"]["confidence"] == "supported"
    assert f["adjudication"]["caused_by"] == ["extraction_validation@bill"]
