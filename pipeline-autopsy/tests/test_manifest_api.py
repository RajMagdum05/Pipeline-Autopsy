import copy
import json
from pathlib import Path
import sys

import yaml
from fastapi.testclient import TestClient

from autopsy.main import app


ROOT = Path(__file__).resolve().parents[2]
HEADERS = {"X-Autopsy-Api-Key": "autopsy-test-static-key"}


def _manifest(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_shared_manifests_register_as_json_and_yaml_and_are_listed():
    with TestClient(app, headers=HEADERS) as client:
        for filename in ("toy-summarizer.yaml", "insurance-claims.yaml"):
            manifest = _manifest(ROOT / "shared-docs" / "manifests" / filename)
            encoded = json.dumps(manifest) if filename.startswith("toy") else yaml.safe_dump(manifest)
            media_type = "application/json" if filename.startswith("toy") else "application/yaml"
            response = client.put(
                f"/v1/pipelines/{manifest['pipeline']}/versions/{manifest['version']}",
                content=encoded,
                headers={**HEADERS, "Content-Type": media_type},
            )
            assert response.status_code == 200, response.text

        listed = client.get("/v1/pipelines", headers=HEADERS)
        assert listed.status_code == 200
        found = {(row["pipeline"], row["version"]) for row in listed.json()["pipelines"]}
        assert {("toy-summarizer", "0.1.0"), ("insurance-claims", "2.0.0")} <= found


def test_invalid_manifest_returns_every_validation_problem_without_detail_wrapper():
    with TestClient(app, headers=HEADERS) as client:
        response = client.put(
            "/v1/pipelines/bad/versions/latest",
            json={"manifest": "wrong", "pipeline": "Bad Name", "version": "latest", "stages": []},
            headers=HEADERS,
        )
    assert response.status_code == 422
    assert "detail" not in response.json()
    problems = response.json()["problems"]
    assert len(problems) >= 4
    assert any("manifest must" in problem for problem in problems)
    assert any("pipeline must" in problem for problem in problems)
    assert any("version must" in problem for problem in problems)
    assert any("stages must" in problem for problem in problems)


def test_reusing_version_with_different_content_returns_conflict():
    manifest = _manifest(ROOT / "shared-docs" / "manifests" / "toy-summarizer.yaml")
    manifest["pipeline"] = "registration-conflict-test"
    with TestClient(app, headers=HEADERS) as client:
        path = f"/v1/pipelines/{manifest['pipeline']}/versions/{manifest['version']}"
        first = client.put(path, json=manifest, headers=HEADERS)
        assert first.status_code == 200, first.text
        changed = copy.deepcopy(manifest)
        changed["description"] = "Different content for the same version"
        second = client.put(path, json=changed, headers=HEADERS)
    assert second.status_code == 409


def test_sdk_cli_registers_through_testclient(tmp_path, capsys):
    sys.path.insert(0, str(ROOT / "autopsy-sdk"))
    from autopsy_sdk.cli import main

    manifest = _manifest(ROOT / "shared-docs" / "manifests" / "toy-summarizer.yaml")
    manifest["pipeline"] = "cli-registration-test"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with TestClient(app, headers=HEADERS) as client:
        result = main(["register", str(path), "--endpoint", "http://testserver", "--key", HEADERS["X-Autopsy-Api-Key"]], client=client)
    assert result == 0
    assert '"pipeline":"cli-registration-test"' in capsys.readouterr().out.replace(" ", "")
