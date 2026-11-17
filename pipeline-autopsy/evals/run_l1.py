"""Replay recorded L1 cases through manifest, ingest, artifacts, worker, and read API."""
import fnmatch
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "pipeline-autopsy"
GOLDEN = Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(BACKEND))


def _assert_case(case_dir, diagnosis, expected):
    assert diagnosis["verdict"] == expected["verdict"], (
        f"verdict: expected {expected['verdict']}, got {diagnosis['verdict']}"
    )
    assert diagnosis["trace_grade"] == expected["trace_grade"], (
        f"trace_grade: expected {expected['trace_grade']}, got {diagnosis['trace_grade']}"
    )
    findings = {
        f"{row['stage']}@{row['item_id']}" if row.get("item_id") else row["stage"]: row
        for row in diagnosis["findings"]
    }
    origins = sorted(key for key, row in findings.items() if row["role"] == "origin")
    assert origins == sorted(expected.get("origins", [])), f"origins: {origins}"
    for key, wanted in expected.get("findings", {}).items():
        actual = findings.get(key)
        assert actual is not None, f"expected finding {key!r} missing"
        for field in ("role", "classification", "confidence"):
            if field in wanted:
                assert actual.get(field) == wanted[field], (
                    f"{key}.{field}: expected {wanted[field]!r}, got {actual.get(field)!r}"
                )
    for pattern in expected.get("must_not_blame", []):
        assert not any(fnmatch.fnmatchcase(key, pattern) and row["role"] == "origin"
                       for key, row in findings.items()), f"unexpected blamed origin matching {pattern!r}"
    evidence_codes = {row["code"] for row in diagnosis["observations"]}
    missing = set(expected.get("required_evidence_codes", [])) - evidence_codes
    assert not missing, f"missing evidence codes: {sorted(missing)}"


def main():
    cases = sorted(path for path in GOLDEN.glob("toy_*") if path.is_dir())
    if not cases:
        print(f"No recorded toy cases found under {GOLDEN}", file=sys.stderr)
        return 2
    for case_dir in cases:
        for required in ("trace.json", "manifest.yaml", "expected.yaml"):
            if not (case_dir / required).is_file():
                print(f"{case_dir.name}: missing {required}", file=sys.stderr)
                return 2

    with tempfile.TemporaryDirectory(prefix="autopsy-l1-") as temporary:
        temp = Path(temporary)
        os.environ["AUTOPSY_DATABASE_URL"] = f"sqlite:///{(temp / 'autopsy.db').as_posix()}"
        os.environ["AUTOPSY_BLOB_DIR"] = str(temp / "blobs")
        os.environ["AUTOPSY_API_KEY"] = "autopsy-l1-local-key"
        os.environ["AUTOPSY_SETTLE_SECONDS"] = "86400"
        os.environ.pop("AUTOPSY_RECORD_DIR", None)

        from fastapi.testclient import TestClient
        from autopsy.db.database import SessionLocal, engine
        from autopsy.worker.jobs import process_due_jobs
        from autopsy.main import app

        headers = {"X-Autopsy-Api-Key": "autopsy-l1-local-key"}
        with TestClient(app, headers=headers) as client:
            for case_dir in cases:
                trace = json.loads((case_dir / "trace.json").read_text(encoding="utf-8"))
                manifest = yaml.safe_load((case_dir / "manifest.yaml").read_text(encoding="utf-8"))
                expected = yaml.safe_load((case_dir / "expected.yaml").read_text(encoding="utf-8"))
                if not isinstance(expected, dict) or expected.get("verdict") == "TODO":
                    print(f"{case_dir.name}: expected.yaml is still a draft", file=sys.stderr)
                    return 2

                response = client.put(
                    f"/v1/pipelines/{manifest['pipeline']}/versions/{manifest['version']}",
                    content=yaml.safe_dump(manifest), headers={**headers, "Content-Type": "application/yaml"},
                )
                assert response.status_code == 200, f"{case_dir.name}: manifest: {response.text}"
                response = client.post("/v1/traces", json=trace, headers=headers)
                assert response.status_code == 200, f"{case_dir.name}: ingest: {response.text}"

                for artifact_path in sorted((case_dir / "artifacts").glob("*.json")):
                    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                    response = client.post("/v1/artifacts", json=artifact, headers=headers)
                    assert response.status_code in (200, 201), (
                        f"{case_dir.name}: artifact {artifact_path.name}: {response.text}"
                    )

                processed = process_due_jobs(
                    SessionLocal, now=datetime.now(timezone.utc) + timedelta(days=2)
                )
                assert processed >= 1, f"{case_dir.name}: no diagnosis job was processed"
                execution_id = case_dir.name
                response = client.get(f"/v1/executions/{execution_id}/diagnosis", headers=headers)
                assert response.status_code == 200, f"{case_dir.name}: diagnosis: {response.text}"
                _assert_case(case_dir, response.json(), expected)
                print(f"PASS {case_dir.name}: {expected['verdict']}")
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
