"""Golden cases for rca_reference.py (verbatim copy of Project doc claude/reference/test_golden.py)."""
import copy
import itertools

import pytest

from rca_reference import artifact_id, diagnose

ICD = r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$"
INSURANCE = {
    "pipeline": "insurance-claims", "version": "1.0.0",
    "external_inputs": ["source_document"],
    "stages": [
        {"name": "document_processing", "consumes": ["source_document"], "produces": ["ocr_text"]},
        {"name": "information_extraction", "consumes": ["ocr_text"], "produces": ["extracted_entities"]},
        {"name": "rule_engine", "consumes": ["extracted_entities"], "produces": ["decision"]},
        {"name": "final_result", "consumes": ["decision"], "produces": ["claim_result"]},
    ],
    "artifacts": {
        "extracted_entities": {
            "schema": {"type": "object", "required": ["diagnosis_code", "claim_amount", "patient_name"],
                       "properties": {"diagnosis_code": {"type": "string", "pattern": ICD},
                                      "claim_amount": {"type": "number", "exclusiveMinimum": 0}}},
            "consistency": [{"id": "extraction.grounded_in_ocr", "validator": "grounded_fields",
                             "source": "ocr_text", "fields": ["diagnosis_code", "claim_amount", "patient_name"]}],
        },
        "claim_result": {
            "consistency": [{"id": "final.matches_decision", "validator": "equals_upstream",
                             "source": "decision", "fields": ["decision"]}],
        },
    },
}
TOY = {
    "pipeline": "toy-summarizer", "version": "0.1.0", "external_inputs": ["raw"],
    "stages": [
        {"name": "fetch", "consumes": ["raw"], "produces": ["page"]},
        {"name": "summarize", "consumes": ["page"], "produces": ["summary"]},
        {"name": "publish", "consumes": ["summary"], "produces": ["post"]},
    ],
    "artifacts": {"page": {"schema": {"type": "object", "required": ["title", "body"],
                                      "properties": {"body": {"type": "string", "minLength": 20}}}}},
}


class Run:
    def __init__(self, manifest):
        self.m, self.spans, self.store, self.n = manifest, [], {}, itertools.count(1)
        self.base = {"pipeline.name": manifest["pipeline"], "pipeline.version": manifest["version"],
                     "execution.id": "exec_1", "execution.entity_id": "CLM-1"}
        self.root = self._span("execution", None, {"autopsy.role": "execution"})

    def _span(self, name, parent, attrs, status="OK", events=None):
        s = {"span_id": f"s{next(self.n)}", "parent": parent, "name": name, "status": status,
             "attrs": {**self.base, **attrs}, "events": events or [], "start": len(self.spans)}
        self.spans.append(s)
        return s

    def put(self, kind, content):
        aid = artifact_id(content, kind, "exec_1")
        self.store[aid] = {"kind": kind, "content": content}
        return aid

    def stage(self, name, inputs, outputs=(), status="success", attempt=1, err=None, checks=()):
        attrs = {"autopsy.role": "stage", "stage.name": name, "stage.status": status, "stage.attempt": attempt,
                 "input.artifact_ids": list(inputs), "output.artifact_ids": list(outputs)}
        if err:
            attrs.update({"error.type": err[0], "error.message": err[1], "error.class": err[2]})
        events = [{"name": "autopsy.check", "attrs": c} for c in checks]
        s = self._span(name, self.root["span_id"], attrs, "ERROR" if status == "failed" else "OK", events)
        if status == "failed":
            self.root["status"] = "ERROR"
        return s

    def op(self, name, parent, err=None):
        attrs = {"autopsy.role": "operation"}
        if err:
            attrs.update({"error.type": err[0], "error.message": err[1], "error.class": err[2]})
        return self._span(name, parent["span_id"], attrs, "ERROR" if err else "OK")

    def result(self):
        return diagnose(self.spans, self.store, self.m)


def check(cid, result, target=None, fld=None, observed=None, expected=None):
    return {"check.id": cid, "check.kind": "threshold", "check.result": result, "check.target_artifact_id": target,
            "check.field": fld, "check.observed": observed, "check.expected": expected, "check.action": "continued"}


GOOD_OCR = "Patient: Asha Rao. Diagnosis J18.9 pneumonia. Total 1200 INR."
BAD_OCR = "Patient: Asha Rao. Diagnosis XYZ pneum0nia. Total 1200 INR."
GOOD_ENT = {"diagnosis_code": "J18.9", "claim_amount": 1200, "patient_name": "Asha Rao"}
BAD_ENT = {"diagnosis_code": "XYZ", "claim_amount": 1200, "patient_name": "Asha Rao"}
NO_RULE = ("RuleNotFound", "No matching policy rule", "data")
TIMEOUT = ("TimeoutError", "policy service timed out", "infra")


def insurance(ocr=GOOD_OCR, ent=GOOD_ENT, ocr_check=None, rule="ok", final="ok", decision="approved",
              final_decision=None, link_rule_input=True):
    r = Run(INSURANCE)
    doc = r.put("source_document", {"file": "claim.pdf"})
    o = r.put("ocr_text", {"text": ocr})
    r.stage("document_processing", [doc], [o],
            checks=[check("ocr.confidence", ocr_check, o, observed=0.61, expected=">=0.80")] if ocr_check else [])
    e = r.put("extracted_entities", ent)
    r.stage("information_extraction", [o], [e])
    rule_in = [e] if link_rule_input else []
    if rule == "ok":
        d = r.put("decision", {"decision": decision})
        r.stage("rule_engine", rule_in, [d])
    else:
        r.stage("rule_engine", rule_in, [], status="failed", err=rule)
        if final == "failed":
            r.stage("final_result", [], [], status="failed", err=("MissingDecision", "no decision", "data"))
        return r
    c = r.put("claim_result", {"decision": final_decision or decision})
    r.stage("final_result", [d], [c])
    return r


def by_stage(res):
    return {f["stage"]: f for f in res["findings"]}


def origins(res):
    return sorted(f["stage"] for f in res["findings"] if f["role"] == "origin")


def test_01_healthy():
    res = insurance().result()
    assert res["verdict"] == "NO_ISSUE_DETECTED" and res["trace_grade"] == "A" and not res["findings"]


def test_02_healthy_with_retry():
    r = Run(INSURANCE)
    doc = r.put("source_document", {"file": "claim.pdf"}); o = r.put("ocr_text", {"text": GOOD_OCR})
    r.stage("document_processing", [doc], [o])
    r.stage("information_extraction", [o], [], status="failed", attempt=1, err=("RateLimit", "429", "infra"))
    r.root["status"] = "OK"
    e = r.put("extracted_entities", GOOD_ENT); r.stage("information_extraction", [o], [e], attempt=2)
    d = r.put("decision", {"decision": "approved"}); r.stage("rule_engine", [e], [d])
    c = r.put("claim_result", {"decision": "approved"}); r.stage("final_result", [d], [c])
    res = r.result()
    assert res["verdict"] == "NO_ISSUE_DETECTED"
    assert any(o.code == "retried" for o in res["observations"])


def test_03_ocr_garbage_copied_faithfully():
    res = insurance(ocr=BAD_OCR, ent=BAD_ENT, ocr_check="warn", rule=NO_RULE, final="failed").result()
    f = by_stage(res)
    assert res["verdict"] == "ROOT_CAUSE_IDENTIFIED" and origins(res) == ["document_processing"]
    assert f["document_processing"]["classification"] == "OUTPUT_CONTRACT_VIOLATION"
    assert f["document_processing"]["confidence"] == "supported"
    assert f["information_extraction"]["role"] == "propagated"
    assert f["information_extraction"]["classification"] == "INVALID_UPSTREAM_INPUT"
    assert f["rule_engine"]["role"] == "propagated" and f["rule_engine"]["link"] == "strong"
    assert f["final_result"]["role"] == "propagated"
    assert f["final_result"]["classification"] == "DOWNSTREAM_PROPAGATED_SUSPICION"


def test_04_extraction_invents_code():
    res = insurance(ocr=GOOD_OCR, ent=BAD_ENT, rule=NO_RULE).result()
    f = by_stage(res)
    assert origins(res) == ["information_extraction"]
    assert f["information_extraction"]["classification"] == "SOURCE_EVIDENCE_CONTRADICTION"
    assert f["information_extraction"]["confidence"] == "supported"
    assert f["rule_engine"]["role"] == "propagated"
    assert f["final_result"]["role"] == "not_executed"


def test_05_extraction_missing_required_field():
    ent = {"diagnosis_code": "J18.9", "patient_name": "Asha Rao"}
    res = insurance(ent=ent, rule=NO_RULE).result()
    f = by_stage(res)
    assert origins(res) == ["information_extraction"]
    assert f["information_extraction"]["classification"] == "OUTPUT_CONTRACT_VIOLATION"


def test_06_rule_engine_timeout_clean_inputs():
    res = insurance(rule=TIMEOUT).result()
    f = by_stage(res)
    assert origins(res) == ["rule_engine"]
    assert f["rule_engine"]["classification"] == "SERVICE_EXECUTION_FAILURE"
    assert f["final_result"]["role"] == "not_executed" and f["final_result"]["caused_by"] == ["rule_engine"]
    assert "information_extraction" not in f


def test_07_two_independent_origins():
    res = insurance(ocr=GOOD_OCR, ent=BAD_ENT, rule=TIMEOUT).result()
    assert res["verdict"] == "MULTIPLE_ROOT_CAUSES"
    assert origins(res) == ["information_extraction", "rule_engine"]


def test_08_bad_extraction_everything_downstream_succeeds():
    res = insurance(ocr=GOOD_OCR, ent=BAD_ENT).result()
    f = by_stage(res)
    assert origins(res) == ["information_extraction"]
    assert f["rule_engine"]["role"] == "tainted" and f["final_result"]["role"] == "tainted"
    assert f["final_result"]["classification"] == "DOWNSTREAM_PROPAGATED_SUSPICION"


def test_09_final_result_contradicts_decision():
    res = insurance(decision="rejected", final_decision="approved").result()
    f = by_stage(res)
    assert origins(res) == ["final_result"]
    assert f["final_result"]["classification"] == "SOURCE_EVIDENCE_CONTRADICTION"


def test_10_exception_in_sub_operation_blames_stage_not_root():
    r = Run(INSURANCE)
    doc = r.put("source_document", {"file": "claim.pdf"}); o = r.put("ocr_text", {"text": GOOD_OCR})
    r.stage("document_processing", [doc], [o])
    st = r.stage("information_extraction", [o], [], status="failed")
    r.op("llm_call", st, err=("ServiceUnavailable", "503 from model API", "infra"))
    res = r.result()
    f = by_stage(res)
    assert origins(res) == ["information_extraction"]
    assert f["information_extraction"]["classification"] == "SERVICE_EXECUTION_FAILURE"
    assert f["rule_engine"]["role"] == "not_executed" and f["final_result"]["role"] == "not_executed"
    ev = [o for o in res["observations"] if o.id in f["information_extraction"]["evidence"]]
    assert ev[0].span_id != st["span_id"]


def test_11_not_executed_is_impact_not_failure():
    res = insurance(rule=TIMEOUT).result()
    assert by_stage(res)["final_result"]["role"] == "not_executed"
    assert origins(res) == ["rule_engine"]


def test_12_missing_lineage_caps_confidence():
    res = insurance(ocr=GOOD_OCR, ent=BAD_ENT, rule=NO_RULE, link_rule_input=False).result()
    f = by_stage(res)
    assert res["trace_grade"] == "B"
    assert origins(res) == ["information_extraction"]
    assert f["information_extraction"]["confidence"] == "possible"
    assert f["rule_engine"]["link"] == "weak" and f["rule_engine"]["confidence"] == "possible"


def test_13_broken_trace_abstains():
    r = insurance(ocr=GOOD_OCR, ent=BAD_ENT, rule=NO_RULE)
    r.spans = [s for s in r.spans if s["attrs"]["autopsy.role"] != "execution"]
    for s in r.spans[:2]:
        s["attrs"].pop("stage.name")
    res = r.result()
    assert res["verdict"] == "INSUFFICIENT_EVIDENCE" and res["trace_grade"] == "C" and not res["findings"]


def test_14_toy_pipeline_domain_agnostic():
    r = Run(TOY)
    raw = r.put("raw", {"url": "https://example.com"})
    p = r.put("page", {"title": "Hi", "body": "too short"})
    r.stage("fetch", [raw], [p])
    s = r.put("summary", {"text": "..."}); r.stage("summarize", [p], [s])
    r.stage("publish", [s], [], status="failed", err=("ValueError", "summary empty", "data"))
    res = r.result()
    f = by_stage(res)
    assert origins(res) == ["fetch"] and f["fetch"]["classification"] == "OUTPUT_CONTRACT_VIOLATION"
    assert f["summarize"]["role"] == "tainted" and f["publish"]["role"] == "propagated"


def test_15_garbage_ocr_without_any_ocr_check():
    res = insurance(ocr=BAD_OCR, ent=BAD_ENT, rule=NO_RULE).result()
    f = by_stage(res)
    assert origins(res) == ["document_processing"]
    assert f["document_processing"]["confidence"] == "possible"
    assert f["information_extraction"]["role"] == "propagated"


def test_16_stage_rejects_input_nothing_flags_it():
    res = insurance(rule=NO_RULE).result()
    f = by_stage(res)
    assert origins(res) == ["rule_engine"]
    assert f["rule_engine"]["classification"] == "INVALID_UPSTREAM_INPUT"
    assert f["rule_engine"]["confidence"] == "possible" and "Coverage gap" in f["rule_engine"]["note"]


def test_17_ocr_warning_only_downstream_fine():
    res = insurance(ocr_check="warn").result()
    f = by_stage(res)
    assert origins(res) == ["document_processing"] and f["document_processing"]["severity"] == "warn"
    assert f["information_extraction"]["role"] == "tainted"
    assert f["information_extraction"]["confidence"] == "possible"


def test_18_ocr_warning_and_extraction_also_invents():
    ent = {"diagnosis_code": "Q99", "claim_amount": 1200, "patient_name": "Asha Rao"}
    res = insurance(ocr=GOOD_OCR, ent=ent, ocr_check="warn").result()
    assert origins(res) == ["document_processing", "information_extraction"]
    assert by_stage(res)["information_extraction"]["classification"] == "SOURCE_EVIDENCE_CONTRADICTION"


def test_19_consumer_check_implicates_producer():
    r = Run(INSURANCE)
    doc = r.put("source_document", {"file": "claim.pdf"}); o = r.put("ocr_text", {"text": GOOD_OCR})
    r.stage("document_processing", [doc], [o])
    ent = dict(GOOD_ENT, claim_amount=1200); e = r.put("extracted_entities", ent)
    r.stage("information_extraction", [o], [e])
    r.stage("rule_engine", [e], [], status="failed", err=NO_RULE,
            checks=[check("rules.input.policy_number_present", "fail", e, fld="policy_number")])
    res = r.result()
    f = by_stage(res)
    assert origins(res) == ["information_extraction"]
    assert f["rule_engine"]["role"] == "propagated" and f["rule_engine"]["link"] == "strong"


def test_21_unclassified_failure_next_to_bad_input_is_hedged():
    res = insurance(ocr=GOOD_OCR, ent=BAD_ENT, rule=("Boom", "?", None)).result()
    f = by_stage(res)
    assert f["rule_engine"]["role"] == "propagated" and f["rule_engine"]["confidence"] == "possible"


def test_20_every_finding_has_evidence_or_cause():
    for build in (lambda: insurance(ocr=BAD_OCR, ent=BAD_ENT, ocr_check="warn", rule=NO_RULE, final="failed"),
                  lambda: insurance(ocr=GOOD_OCR, ent=BAD_ENT), lambda: insurance(rule=TIMEOUT)):
        res = build().result()
        ids = {o.id for o in res["observations"]}
        for f in res["findings"]:
            assert f["evidence"] or f["caused_by"], f
            assert set(f["evidence"]) <= ids


def _drop_attr(key):
    def m(r):
        for s in r.spans:
            if s["attrs"].get("autopsy.role") == "stage":
                s["attrs"].pop(key, None)
    return m


def _drop_checks(r):
    for s in r.spans:
        s["events"] = []


def _drop_artifact_content(r):
    for aid in [a for a, v in r.store.items() if v["kind"] == "ocr_text"]:
        del r.store[aid]


def _drop_root(r):
    r.spans = [s for s in r.spans if s["attrs"]["autopsy.role"] != "execution"]


def _drop_stage_span(r):
    r.spans = [s for s in r.spans if s["attrs"].get("stage.name") != "information_extraction"]


MUTATIONS = {"drop input ids": _drop_attr("input.artifact_ids"), "drop output ids": _drop_attr("output.artifact_ids"),
             "drop stage.attempt": _drop_attr("stage.attempt"), "drop checks": _drop_checks,
             "drop ocr artifact": _drop_artifact_content, "drop execution span": _drop_root,
             "drop extraction span": _drop_stage_span, "drop error.class": _drop_attr("error.class")}


@pytest.mark.parametrize("name", MUTATIONS)
def test_mutation_never_confidently_wrong(name):
    base = insurance(ocr=BAD_OCR, ent=BAD_ENT, ocr_check="warn", rule=NO_RULE, final="failed")
    truth = origins(base.result())
    r = copy.deepcopy(base)
    MUTATIONS[name](r)
    res = r.result()
    for f in res["findings"]:
        if f["role"] == "origin" and f["stage"] not in truth:
            assert f["confidence"] != "supported", (name, f)
