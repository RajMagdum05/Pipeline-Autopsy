from evals.l2_metrics import format_table, summarize_runs


def test_summarize_runs_reports_rates_and_observability():
    summary = summarize_runs([
        {"attempted": True, "first_pass": True, "fallback": False,
         "tokens_in": 100, "tokens_out": 40, "latency_ms": 120},
        {"attempted": True, "first_pass": False, "fallback": True,
         "tokens_in": 80, "tokens_out": 20, "latency_ms": 180},
        {"attempted": False},
    ], faithfulness=(19, 20))

    assert summary == {
        "attempted_cases": 2,
        "first_pass_rate": "50.0% (1/2)",
        "fallback_rate": "50.0% (1/2)",
        "faithfulness": "95.0% (19/20)",
        "tokens": "180 in / 60 out",
        "latency": "150.0 ms mean",
    }


def test_summarize_runs_marks_empty_denominators_as_unavailable():
    summary = summarize_runs([], faithfulness=(0, 0))

    assert summary["attempted_cases"] == 0
    assert summary["first_pass_rate"] == "N/A"
    assert summary["fallback_rate"] == "N/A"
    assert summary["faithfulness"] == "N/A (judge not run)"
    assert summary["tokens"] == "N/A (no LLM attempts)"
    assert summary["latency"] == "N/A (no LLM attempts)"


def test_format_table_keeps_l1_separate_and_lists_exclusions():
    report = format_table(
        summarize_runs([]), eligible_cases=0, template_cases=0,
        exclusions=[("draft_case", "expected evidence is not approved")],
    )

    assert "0 eligible case(s)" in report
    assert "| Guardrail first-pass rate | N/A |" in report
    assert "| Adversarial guardrails | separate L0 suite |" in report
    assert "Excluded cases: 1" in report
    assert "draft_case: expected evidence is not approved" in report
    assert "separate L1 gate" in report
