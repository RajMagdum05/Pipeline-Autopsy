import shutil
from pathlib import Path

import yaml

from evals.run_l2 import evaluate_cases


EVALS = Path(__file__).resolve().parents[2] / "evals"


def test_default_l2_corpus_excludes_drafts_and_healthy_case():
    rows, exclusions = evaluate_cases(EVALS / "golden")

    assert rows == []
    assert {name for name, _ in exclusions} == {
        "toy_healthy", "toy_publish_timeout", "toy_short_body"
    }
    assert all("l2_approved: true" in reason or "no expected finding" in reason
               for _, reason in exclusions)


def test_approved_recorded_findings_case_generates_deterministic_baseline(tmp_path):
    case = tmp_path / "toy_short_body"
    shutil.copytree(EVALS / "golden" / "toy_short_body", case)
    expected_path = case / "expected.yaml"
    expected = yaml.safe_load(expected_path.read_text(encoding="utf-8"))
    expected["l2_approved"] = True
    expected_path.write_text(yaml.safe_dump(expected, sort_keys=False), encoding="utf-8")

    rows, exclusions = evaluate_cases(tmp_path)

    assert exclusions == []
    assert len(rows) == 1
    assert rows[0]["attempted"] is False
    assert any("fetch" in line for line in rows[0]["template"]["narrative"])
    assert rows[0]["template"]
