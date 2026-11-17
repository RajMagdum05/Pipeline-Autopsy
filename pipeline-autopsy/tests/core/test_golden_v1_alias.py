import test_golden as golden

from autopsy.core import diagnose


def _to_v1(spans):
    aliases = {
        "pipeline.run.id": "execution.id",
        "pipeline.entity.id": "execution.entity_id",
        "pipeline.stage.name": "stage.name",
        "pipeline.stage.status": "stage.status",
        "pipeline.stage.attempt": "stage.attempt",
        "pipeline.artifact.input_ids": "input.artifact_ids",
        "pipeline.artifact.output_ids": "output.artifact_ids",
        "pipeline.span.role": "autopsy.role",
        "pipeline.error.class": "error.class",
    }
    legacy = []
    for span in spans:
        old = {**span, "attrs": dict(span["attrs"]), "events": []}
        for current, previous in aliases.items():
            if current in old["attrs"]:
                old["attrs"][previous] = old["attrs"].pop(current)
        for event in span.get("events", []):
            old_event = {**event, "attrs": dict(event.get("attrs", {}))}
            if old_event.get("name") == "pipeline.check":
                old_event["name"] = "autopsy.check"
            for key in list(old_event["attrs"]):
                if key.startswith("pipeline.check."):
                    old_event["attrs"]["check." + key[len("pipeline.check."):]] = old_event["attrs"].pop(key)
            old["events"].append(old_event)
        legacy.append(old)
    return legacy


def _origins(result):
    return sorted(finding["stage"] for finding in result["findings"] if finding["role"] == "origin")


def _cases():
    return [
        ("01", lambda: golden.insurance()),
        ("03", lambda: golden.insurance(ocr=golden.BAD_OCR, ent=golden.BAD_ENT, ocr_check="warn",
                                         rule=golden.NO_RULE, final="failed")),
        ("04", lambda: golden.insurance(ocr=golden.GOOD_OCR, ent=golden.BAD_ENT, rule=golden.NO_RULE)),
        ("07", lambda: golden.insurance(ocr=golden.GOOD_OCR, ent=golden.BAD_ENT, rule=golden.TIMEOUT)),
        ("12", lambda: golden.insurance(ocr=golden.GOOD_OCR, ent=golden.BAD_ENT, rule=golden.NO_RULE,
                                         link_rule_input=False)),
        ("13", lambda: _broken_trace()),
    ]


def _broken_trace():
    run = golden.insurance(ocr=golden.GOOD_OCR, ent=golden.BAD_ENT, rule=golden.NO_RULE)
    run.spans = [span for span in run.spans if span["attrs"].get("pipeline.span.role") != "execution"]
    for span in run.spans[:2]:
        span["attrs"].pop("pipeline.stage.name", None)
    return run


def test_selected_golden_cases_match_through_v1_aliases():
    for case_id, factory in _cases():
        run = factory()
        expected = run.result()
        actual = diagnose(_to_v1(run.spans), run.store, run.m)
        assert actual["verdict"] == expected["verdict"], case_id
        assert _origins(actual) == _origins(expected), case_id
