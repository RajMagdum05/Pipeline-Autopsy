import ast
import inspect
import json
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from opentelemetry import trace

import autopsy_sdk as autopsy
from autopsy_sdk.errors import AutopsyUsageError
from autopsy_sdk.propagate import submit
from autopsy_sdk.testing import InMemoryCapture, assert_contract, validate_trace as vendored_validate_trace
from autopsy_sdk import api as sdk_api


TOY = {
    "pipeline": "toy-summarizer",
    "version": "0.1.0",
    "stages": [
        {"name": "fetch", "scope": "run", "consumes": ["raw"], "produces": ["page"]},
        {"name": "summarize", "scope": "run", "consumes": ["page"], "produces": ["summary"]},
        {"name": "publish", "scope": "run", "consumes": ["summary"], "produces": ["post"]},
    ],
}


def _span_by_role(spans, role):
    return next(span for span in spans if span.attributes.get("pipeline.span.role") == role)


def test_normal_stage_has_complete_contract_attributes_and_exit_status():
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    with InMemoryCapture() as capture:
        with autopsy.run(entity_id="entity-1", items={"item-1": "source"}, run_id="run-1"):
            with autopsy.stage("fetch", item_id="item-1", item_role="source", inputs=["raw-id"]) as stage:
                assert "pipeline.stage.status" not in stage.raw_span.attributes
    span = _span_by_role(capture.spans, "stage")
    assert span.attributes["pipeline.name"] == "toy-summarizer"
    assert span.attributes["pipeline.version"] == "0.1.0"
    assert span.attributes["pipeline.run.id"] == "run-1"
    assert span.attributes["pipeline.stage.name"] == "fetch"
    assert span.attributes["pipeline.stage.status"] == "success"
    assert span.attributes["pipeline.stage.attempt"] == 1
    assert span.attributes["pipeline.stage.item_id"] == "item-1"
    assert span.attributes["pipeline.artifact.input_ids"] == ("raw-id",)
    assert span.attributes["pipeline.artifact.output_ids"] == ()


def test_stage_exception_is_classified_sanitized_and_reraised_unchanged():
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    error = ValueError("invalid for alice@example.com phone +1 (415) 555-1234 id 123456789012")
    with InMemoryCapture() as capture:
        with pytest.raises(ValueError) as caught:
            with autopsy.run(run_id="run-error"):
                with autopsy.stage("fetch"):
                    raise error
    assert caught.value is error
    span = _span_by_role(capture.spans, "stage")
    assert span.attributes["pipeline.stage.status"] == "failed"
    assert span.attributes["pipeline.error.class"] == "data"
    assert span.attributes["error.type"] == "ValueError"
    assert span.status.description is not None and len(span.status.description) <= 500
    assert "alice@example.com" not in span.status.description
    assert "415" not in span.status.description
    assert "123456789012" not in span.status.description
    assert not span.events


def test_record_artifact_matches_contract_id_and_updates_output_ids():
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    content = {"z": "café", "a": 1}
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="run-artifact"):
            with autopsy.stage("fetch", item_id="item-4") as stage:
                artifact = stage.record_artifact("page", content)
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"run-artifact\x00page\x00item-4\x00" + canonical).hexdigest()[:16]
    assert artifact == f"art_{digest}"
    span = _span_by_role(capture.spans, "stage")
    assert span.attributes["pipeline.artifact.output_ids"] == (artifact,)


def test_artifact_ids_change_with_kind_or_item():
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    with autopsy.run(run_id="run-different"):
        ids = {
            autopsy.artifact_id("page", {"title": "same"}, "item-1"),
            autopsy.artifact_id("summary", {"title": "same"}, "item-1"),
            autopsy.artifact_id("page", {"title": "same"}, "item-2"),
        }
    assert len(ids) == 3


def test_check_event_has_contract_fields_and_truncates_observed_values():
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="run-check"):
            with autopsy.stage("fetch") as stage:
                stage.check("page.short", kind="threshold", result="warn", action="review",
                            target="artifact-1", field="body.length", observed="x" * 90, expected="20")
    span = _span_by_role(capture.spans, "stage")
    event = span.events[0]
    assert event.name == "pipeline.check"
    assert event.attributes["pipeline.check.id"] == "page.short"
    assert event.attributes["pipeline.check.kind"] == "threshold"
    assert event.attributes["pipeline.check.result"] == "warn"
    assert event.attributes["pipeline.check.action"] == "review"
    assert event.attributes["pipeline.check.target_artifact_id"] == "artifact-1"
    assert event.attributes["pipeline.check.field"] == "body.length"
    assert len(event.attributes["pipeline.check.observed"]) == 64
    assert event.attributes["pipeline.check.expected"] == "20"


def test_nested_stage_is_operation_by_default_and_usage_error_in_strict_mode(monkeypatch):
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="run-nested"):
            with autopsy.stage("fetch"):
                with autopsy.stage("nested"):
                    pass
    nested = next(span for span in capture.spans if span.name == "nested")
    assert nested.attributes["pipeline.span.role"] == "operation"

    monkeypatch.setenv("AUTOPSY_STRICT", "true")
    with pytest.raises(AutopsyUsageError):
        with autopsy.run(run_id="run-strict"):
            with autopsy.stage("fetch"):
                with autopsy.stage("nested"):
                    pass


def test_no_provider_is_a_noop_and_thread_propagation_keeps_context():
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    with autopsy.run(run_id="run-no-provider"):
        assert not trace.get_current_span().is_recording()
        with autopsy.stage("fetch"):
            assert not trace.get_current_span().is_recording()
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="run-thread"):
            with ThreadPoolExecutor(max_workers=1) as executor:
                active = submit(executor, lambda: trace.get_current_span().get_span_context().is_valid).result()
    assert active is True
    assert len(capture.spans) == 1


def test_disabled_sdk_emits_zero_spans(monkeypatch):
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    monkeypatch.setenv("AUTOPSY_ENABLED", "false")
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="run-disabled"):
            with autopsy.stage("fetch"):
                autopsy.check("ignored", kind="threshold", result="pass", action="continued")
    assert capture.spans == ()


def test_emitted_spans_pass_vendored_contract_against_toy_manifest():
    autopsy.set_pipeline("toy-summarizer", "0.1.0")
    with InMemoryCapture() as capture:
        with autopsy.run(run_id="run-contract"):
            with autopsy.stage("fetch", inputs=["raw-1"]) as stage:
                stage.record_artifact("page", {"title": "Hello", "body": "A sufficiently long body."})
            with autopsy.stage("summarize", inputs=["page-1"]) as stage:
                stage.record_artifact("summary", {"text": "A summary."})
            with autopsy.stage("publish", inputs=["summary-1"]):
                pass
    assert assert_contract(capture.spans, TOY) == "A"


def test_vendored_validate_trace_source_stays_identical_to_core():
    repo_root = Path(__file__).resolve().parents[2]
    core_source = (repo_root / "pipeline-autopsy" / "autopsy" / "core" / "contract.py").read_text(encoding="utf-8")
    function = next(node for node in ast.parse(core_source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "validate_trace")
    core_function_source = ast.get_source_segment(core_source, function).strip()
    assert inspect.getsource(vendored_validate_trace).strip() == core_function_source


def test_internal_instrumentation_failure_warns_once_and_does_not_break_host(monkeypatch, caplog):
    class BrokenTracer:
        def start_as_current_span(self, *_args, **_kwargs):
            raise RuntimeError("internal test failure")

    monkeypatch.setattr(sdk_api, "_tracer", lambda: BrokenTracer())
    completed = []
    with caplog.at_level(logging.WARNING, logger="autopsy_sdk"):
        with autopsy.run(run_id="run-sdk-error"):
            with autopsy.stage("fetch"):
                completed.append(True)
    warnings = [record for record in caplog.records if record.name == "autopsy_sdk" and record.levelno == logging.WARNING]
    assert completed == [True]
    assert len(warnings) == 1
