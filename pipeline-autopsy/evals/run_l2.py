"""Evaluate explanations only for explicitly approved recorded findings cases.

Default mode is deterministic and makes no model calls. Use ``--live`` only
after supplying AUTOPSY_LLM_MODEL and GEMINI_API_KEY (or GOOGLE_API_KEY).
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(ROOT))


def _core_spans_and_items(trace_payload):
    from autopsy.ingest.otlp import OTLPAdapter

    traces = OTLPAdapter().parse_trace_request(trace_payload)
    spans, items = [], {}
    for trace in traces:
        resource = {"attributes": trace.get("resource_attributes") or {}}
        for row in trace.get("spans", []):
            spans.append({
                "trace_id": trace["trace_id"], "span_id": row["span_id"],
                "parent": row.get("parent_span_id"), "name": row["operation_name"],
                "kind": row["kind"], "start": row["start_time"], "end": row["end_time"],
                "status": row["status_code"], "status_message": row.get("status_message"),
                "attrs": row.get("attributes") or {}, "resource": resource,
                "events": [{"name": event.get("name"), "attrs": event.get("attributes") or {},
                            "timestamp": event.get("timestamp")}
                           for event in row.get("events") or []],
                "links": row.get("links") or [],
                "dropped_attributes": row.get("dropped_attributes", 0),
                "dropped_events": row.get("dropped_events", 0),
            })
    root = next((span for span in spans if span["attrs"].get("autopsy.role") == "execution"), None)
    encoded = (root or {}).get("attrs", {}).get("pipeline.run.items", [])
    if isinstance(encoded, dict):
        items = {str(item): str(role) for item, role in encoded.items()}
    elif isinstance(encoded, list):
        for item in encoded:
            if isinstance(item, str) and ":" in item:
                item_id, role = item.rsplit(":", 1)
                if item_id and role:
                    items[item_id] = role
    if not items:
        for span in spans:
            attrs = span["attrs"]
            item_id = attrs.get("pipeline.stage.item_id") or attrs.get("item.id")
            role = attrs.get("pipeline.stage.item_role") or attrs.get("item.role")
            if item_id is not None and role is not None:
                items[str(item_id)] = str(role)
    return spans, items


def _load_case(case_dir):
    for required in ("trace.json", "manifest.yaml", "expected.yaml"):
        if not (case_dir / required).is_file():
            return None, f"missing {required}"
    manifest = yaml.safe_load((case_dir / "manifest.yaml").read_text(encoding="utf-8"))
    expected = yaml.safe_load((case_dir / "expected.yaml").read_text(encoding="utf-8"))
    if not isinstance(expected, dict) or expected.get("verdict") in (None, "TODO"):
        return None, "expected.yaml has no reviewed verdict"
    if expected.get("l2_approved") is not True:
        return None, "expected.yaml lacks owner approval (l2_approved: true)"
    if not expected.get("findings") or not expected.get("required_evidence_codes"):
        return None, "case has no expected finding and evidence code"

    from autopsy.core.fanout import diagnose
    from autopsy.explain.bundle import build_bundle
    from autopsy.explain.template import build_template

    trace = json.loads((case_dir / "trace.json").read_text(encoding="utf-8"))
    spans, items = _core_spans_and_items(trace)
    artifacts = {}
    artifact_dir = case_dir / "artifacts"
    if artifact_dir.is_dir():
        for artifact_path in sorted(artifact_dir.glob("*.json")):
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifacts[artifact["id"]] = {
                "kind": artifact.get("kind"), "content": artifact.get("content"),
                "redacted": artifact.get("redacted", False),
            }
    result = diagnose(spans, artifacts, manifest, items if items else None)
    mismatch = _expectation_mismatch(result, expected)
    if mismatch:
        return None, f"recorded diagnosis does not satisfy expected.yaml: {mismatch}"
    evidence_level = (manifest.get("evidence") or {}).get("level", "E1")
    bundle = build_bundle(result, artifacts, evidence_level=evidence_level)
    bundle["remediation"] = []  # golden fixtures do not persist retrieved playbooks
    return {"bundle": bundle, "template": build_template(bundle), "expected": expected}, None


def _expectation_mismatch(result, expected):
    if result.get("verdict") != expected.get("verdict"):
        return f"verdict expected {expected.get('verdict')!r}, got {result.get('verdict')!r}"
    if result.get("trace_grade") != expected.get("trace_grade"):
        return f"trace grade expected {expected.get('trace_grade')!r}, got {result.get('trace_grade')!r}"
    if "origins" in expected:
        actual_origins = sorted(row.get("stage") for row in result.get("findings", [])
                                if row.get("role") == "origin")
        if actual_origins != sorted(expected.get("origins") or []):
            return f"origins expected {expected.get('origins')!r}, got {actual_origins!r}"
    findings = {
        f"{row.get('stage')}@{row.get('item_id')}" if row.get("item_id") else row.get("stage"): row
        for row in result.get("findings", [])
    }
    for key, wanted in (expected.get("findings") or {}).items():
        actual = findings.get(key)
        if actual is None:
            return f"expected finding {key!r} is absent"
        for field in ("role", "classification", "confidence"):
            if field in wanted and actual.get(field) != wanted[field]:
                return f"{key}.{field} expected {wanted[field]!r}, got {actual.get(field)!r}"
    for code in expected.get("required_evidence_codes") or []:
        if code not in {row.code for row in result.get("observations", [])}:
            return f"required evidence code {code!r} is absent"
    for pattern in expected.get("must_not_blame") or []:
        import fnmatch
        if any(fnmatch.fnmatchcase(key, pattern) and row.get("role") == "origin"
               for key, row in findings.items()):
            return f"unexpected origin matches {pattern!r}"
    return None


def evaluate_cases(golden_dir, *, llm_client=None):
    from autopsy.explain.service import explain

    rows, exclusions = [], []
    cases = sorted(path for path in Path(golden_dir).iterdir() if path.is_dir())
    for case_dir in cases:
        loaded, reason = _load_case(case_dir)
        if reason:
            exclusions.append((case_dir.name, reason))
            continue
        row = {"name": case_dir.name, "template": loaded["template"], "attempted": False}
        if llm_client is not None:
            explanation = explain(loaded["bundle"], llm_client)
            attempt_logs = [entry for entry in explanation.get("guardrail_log", [])
                            if isinstance(entry, dict) and isinstance(entry.get("attempt"), int)]
            row["attempted"] = bool(attempt_logs)
            row["first_pass"] = bool(attempt_logs and attempt_logs[0].get("outcome") == "accepted")
            row["fallback"] = bool(row["attempted"] and explanation.get("source") == "template")
            row["tokens_in"] = explanation.get("tokens_in")
            row["tokens_out"] = explanation.get("tokens_out")
            row["latency_ms"] = explanation.get("latency_ms")
            row["explanation"] = explanation
        rows.append(row)
    return rows, exclusions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="call the configured Gemini model (requires explicit model and API key env vars)")
    parser.add_argument("--golden-dir", type=Path, default=GOLDEN,
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    client = None
    if args.live:
        from autopsy.explain.llm import client_from_env
        client = client_from_env()
        if client is None:
            print("Live mode requested but AUTOPSY_LLM_MODEL and GEMINI_API_KEY (or GOOGLE_API_KEY) are required.",
                  file=sys.stderr)
            return 2

    from evals.l2_metrics import format_table, summarize_runs

    rows, exclusions = evaluate_cases(args.golden_dir, llm_client=client)
    summary = summarize_runs(rows)
    print(format_table(summary, eligible_cases=len(rows), template_cases=len(rows), exclusions=exclusions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
