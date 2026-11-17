from copy import deepcopy
import hashlib
import json

from autopsy.core import artifact_id
from autopsy.core.normalize import ALIASES, normalize


def test_v3_span_and_check_fields_normalize_to_internal_names():
    span = {
        "span_id": "s1",
        "attrs": {
            "pipeline.run.id": "run-v3",
            "pipeline.entity.id": "entity-v3",
            "pipeline.span.role": "stage",
            "pipeline.stage.name": "extract",
            "pipeline.stage.status": "success",
            "pipeline.stage.attempt": 2,
            "pipeline.artifact.input_ids": ["in"],
            "pipeline.artifact.output_ids": ["out"],
            "pipeline.error.class": "data",
        },
        "events": [{"name": "pipeline.check", "attrs": {
            "pipeline.check.id": "fields.valid", "pipeline.check.result": "fail",
        }}],
    }
    before = deepcopy(span)

    result = normalize([span])[0]

    assert result["attrs"]["execution.id"] == "run-v3"
    assert result["attrs"]["execution.entity_id"] == "entity-v3"
    assert result["attrs"]["autopsy.role"] == "stage"
    assert result["attrs"]["stage.name"] == "extract"
    assert result["attrs"]["stage.status"] == "success"
    assert result["attrs"]["stage.attempt"] == 2
    assert result["attrs"]["input.artifact_ids"] == ["in"]
    assert result["attrs"]["output.artifact_ids"] == ["out"]
    assert result["attrs"]["error.class"] == "data"
    assert result["events"][0]["name"] == "autopsy.check"
    assert result["events"][0]["attrs"]["check.id"] == "fields.valid"
    assert result["events"][0]["attrs"]["check.result"] == "fail"
    assert span == before


def test_v3_alias_wins_when_legacy_alias_is_also_present():
    attrs = {"pipeline.stage.name": "new", "stage.name": "old"}
    assert normalize([{"attrs": attrs}])[0]["attrs"]["stage.name"] == "new"


def test_v1_fields_are_preserved_as_internal_names():
    span = {"attrs": {legacy: f"value-{index}" for index, legacy in enumerate(ALIASES.values())}}
    result = normalize([span])[0]["attrs"]
    assert all(result[key] == value for key, value in span["attrs"].items())


def test_run_id_resolution_prefers_span_then_resource_then_trace():
    spans = [
        {"attrs": {"pipeline.run.id": "span-v3", "execution.id": "span-v1"},
         "resource": {"attributes": {"pipeline.run.id": "resource-v3"}}, "trace_id": "trace-1"},
        {"attrs": {"execution.id": "span-v1"},
         "resource": {"attributes": {"pipeline.run.id": "resource-v3"}}, "trace_id": "trace-2"},
        {"attrs": {}, "resource": {"attributes": {"execution.id": "resource-v1"}}, "trace_id": "trace-3"},
        {"attrs": {}, "trace_id": "trace-4"},
    ]
    result = normalize(spans)
    assert [span["attrs"]["execution.id"] for span in result] == [
        "span-v3", "span-v1", "resource-v1", "trace:trace-4",
    ]


def test_missing_run_id_without_trace_id_stays_missing():
    assert "execution.id" not in normalize([{"attrs": {}}])[0]["attrs"]


def test_artifact_ids_follow_v3_canonical_bytes_and_include_item_id():
    content = {"label": "café", "number": 3}
    item_id = "item-7"
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"run-1\x00facts\x00item-7\x00" + canonical).hexdigest()[:16]
    assert artifact_id(content, "facts", "run-1", item_id) == f"art_{digest}"
    assert artifact_id(content, "facts", "run-1", "item-8") != f"art_{digest}"


def test_artifact_ids_encode_strings_and_bytes_as_raw_utf8():
    assert artifact_id("café", "text", "run-1") == artifact_id("café".encode("utf-8"), "text", "run-1")

