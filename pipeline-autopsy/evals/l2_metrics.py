"""Small, explicit metric helpers for the explanation-only L2 evaluation."""

from statistics import mean


def _percent(numerator, denominator):
    if denominator <= 0:
        return "N/A"
    return f"{100 * numerator / denominator:.1f}% ({numerator}/{denominator})"


def summarize_runs(rows, *, faithfulness=None):
    """Summarize recorded LLM attempts without folding diagnosis accuracy into L2."""
    attempts = [row for row in rows if row.get("attempted")]
    first_pass = sum(row.get("first_pass") is True for row in attempts)
    fallback = sum(row.get("fallback") is True for row in attempts)
    token_rows = [row for row in attempts if row.get("tokens_in") is not None
                  or row.get("tokens_out") is not None]
    latency_rows = [row["latency_ms"] for row in attempts if row.get("latency_ms") is not None]
    return {
        "attempted_cases": len(attempts),
        "first_pass_rate": _percent(first_pass, len(attempts)),
        "fallback_rate": _percent(fallback, len(attempts)),
        "faithfulness": (_percent(faithfulness[0], faithfulness[1])
                         if faithfulness and faithfulness[1] else "N/A (judge not run)"),
        "tokens": (f"{sum(row.get('tokens_in') or 0 for row in token_rows)} in / "
                   f"{sum(row.get('tokens_out') or 0 for row in token_rows)} out"
                   if token_rows else "N/A (no LLM attempts)"),
        "latency": (f"{mean(latency_rows):.1f} ms mean" if latency_rows else "N/A (no LLM attempts)"),
    }


def format_table(summary, *, eligible_cases, template_cases, exclusions):
    """Render a concise report with denominators and non-sample exclusions."""
    rows = [
        ("Eligible recorded cases with findings", str(eligible_cases), "L2 sample"),
        ("Template explanations generated", str(template_cases), "deterministic baseline"),
        ("Guardrail first-pass rate", summary["first_pass_rate"], ">= 90%"),
        ("Template fallback rate", summary["fallback_rate"], "< 5%"),
        ("Faithfulness (model-assisted judge)", summary["faithfulness"], ">= 95%"),
        ("Tokens (input / output)", summary["tokens"], "report when available"),
        ("Latency", summary["latency"], "report when available"),
        ("Adversarial guardrails", "separate L0 suite", "10/10 rejected"),
    ]
    lines = [
        f"L2 explanation evaluation -- {eligible_cases} eligible case(s); "
        f"{summary['attempted_cases']} LLM attempt(s)",
        "",
        "| Metric | Result | Target / method |",
        "|---|---:|---|",
    ]
    lines.extend(f"| {name} | {value} | {target} |" for name, value, target in rows)
    lines.extend(["", f"Excluded cases: {len(exclusions)}"])
    if exclusions:
        lines.extend(f"- {name}: {reason}" for name, reason in exclusions)
    else:
        lines.append("- None")
    lines.extend([
        "",
        "L2 measures explanation quality only; diagnosis correctness remains the separate L1 gate.",
        "Faithfulness is N/A unless a judge output is supplied; a model judge is advisory, not ground truth.",
    ])
    return "\n".join(lines)


__all__ = ["format_table", "summarize_runs"]
