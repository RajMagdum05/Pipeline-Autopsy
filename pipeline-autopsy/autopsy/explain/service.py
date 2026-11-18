"""Explanation orchestration: optional guarded LLM draft, else the template (ADR-07).

    for attempt in (1, 2):
        draft = llm(bundle, violations_from_previous)
        violations = guardrails(draft, bundle)
        if not violations: publish(draft, source="llm")
    else:
        publish(template(bundle), source="template")

The bundle and the diagnosis are read-only here. Only prose is produced; origin,
roles, classification, confidence and verdict always come from the core.
"""

import json
import time

from autopsy.explain.guardrails import validate_draft
from autopsy.explain.template import build_template


MAX_ATTEMPTS = 2
_FAULT_ROLES = frozenset({"origin", "propagated", "tainted", "not_executed", "missing"})


def needs_llm(bundle):
    """Healthy runs (no non-healthy findings) never call the LLM."""
    return any(isinstance(f, dict) and f.get("role") in _FAULT_ROLES
               for f in bundle.get("findings") or [])


def _template_result(bundle, log, *, model=None, tokens_in=None, tokens_out=None, latency_ms=None):
    explanation = build_template(bundle)
    explanation.update(model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                       latency_ms=latency_ms, guardrail_log=log)
    return explanation


def _add(total, value):
    if value is None:
        return total
    return (total or 0) + int(value)


def explain(bundle, client=None, *, clock=time.perf_counter):
    """Return the explanation dict to persist.

    Keys: source ("llm" | "template"), summary, narrative (list[str]), remediation,
    model, tokens_in, tokens_out, latency_ms, guardrail_log. The guardrail log holds
    only attempt numbers, outcomes, violation codes/paths and exception type names.
    """
    if not needs_llm(bundle):
        return _template_result(bundle, [{"event": "skipped", "reason": "no_findings"}])
    if client is None:
        return _template_result(bundle, [{"event": "skipped", "reason": "llm_not_configured"}])

    model = getattr(client, "model", None)
    log, violations = [], []
    tokens_in = tokens_out = None
    latency_ms = 0.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = clock()
        try:
            response = client.draft(bundle, violations)
        except Exception as exc:  # timeout, provider error, missing key at call time
            latency_ms += (clock() - started) * 1000.0
            entry = {"attempt": attempt, "outcome": "error", "error": type(exc).__name__}
            cause = exc.__cause__
            if cause is not None:  # exception type name only; never the message
                entry["cause"] = type(cause).__name__
            log.append(entry)
            break
        latency_ms += (clock() - started) * 1000.0
        model = getattr(response, "model", None) or model
        tokens_in = _add(tokens_in, getattr(response, "tokens_in", None))
        tokens_out = _add(tokens_out, getattr(response, "tokens_out", None))
        violations = validate_draft(getattr(response, "text", None), bundle)
        if not violations:
            log.append({"attempt": attempt, "outcome": "accepted", "violations": []})
            return _llm_result(bundle, response.text, log, model=model, tokens_in=tokens_in,
                               tokens_out=tokens_out, latency_ms=round(latency_ms, 3))
        log.append({"attempt": attempt, "outcome": "rejected",
                    "violations": [violation.as_dict() for violation in violations]})

    log.append({"event": "fallback", "source": "template"})
    return _template_result(bundle, log, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                            latency_ms=round(latency_ms, 3))


def _llm_result(bundle, raw_text, log, **metadata):
    draft = json.loads(raw_text) if isinstance(raw_text, (str, bytes, bytearray)) else raw_text
    template = build_template(bundle)
    return {
        "source": "llm",
        "summary": draft["summary"],
        # Persisted as plain strings to keep the API/UI narrative contract (list[str]).
        "narrative": [item["text"] for item in draft["narrative"]],
        # Remediation shown to users stays the deterministically retrieved playbooks.
        "remediation": template["remediation"],
        "guardrail_log": log,
        **metadata,
    }


__all__ = ["MAX_ATTEMPTS", "explain", "needs_llm"]
