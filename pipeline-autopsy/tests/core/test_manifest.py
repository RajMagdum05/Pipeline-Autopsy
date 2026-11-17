from pathlib import Path

import pytest
import yaml

from autopsy.core.manifest import validate_manifest


def valid_manifest():
    return {
        "manifest": "pipeline-manifest/1",
        "pipeline": "toy-test",
        "version": "1.0.0",
        "evidence": {"level": "E1", "kinds_allowed": ["result"], "retention_days": 7},
        "external_inputs": ["source"],
        "stages": [
            {"name": "fetch", "scope": "run", "consumes": ["source"], "produces": ["result"]},
        ],
        "artifacts": {
            "result": {"schema": {"type": "object"}},
        },
    }


def problem(manifest, snippet):
    return any(snippet in message for message in validate_manifest(manifest))


def test_both_repository_manifests_validate():
    root = Path(__file__).resolve().parents[2]
    for name in ("insurance-claims", "toy-summarizer"):
        manifest = yaml.safe_load((root.parent / "shared-docs" / "manifests" / f"{name}.yaml")
                                  .read_text(encoding="utf-8"))
        assert validate_manifest(manifest) == []


@pytest.mark.parametrize("field", ["manifest", "pipeline", "version", "stages"])
def test_required_top_level_keys_are_reported(field):
    manifest = valid_manifest()
    del manifest[field]
    assert problem(manifest, f"missing required key: {field}")


def test_invalid_names_and_version_are_reported():
    manifest = valid_manifest()
    manifest["pipeline"] = "Bad Name"
    manifest["version"] = "latest"
    manifest["stages"][0]["name"] = "Bad Stage"
    problems = validate_manifest(manifest)
    assert any("pipeline must match" in value for value in problems)
    assert any("version must be a semantic version" in value for value in problems)
    assert any("stages[0].name must match" in value for value in problems)


def test_each_kind_may_have_only_one_producer():
    manifest = valid_manifest()
    manifest["stages"].append({"name": "other", "scope": "run", "consumes": ["source"],
                                "produces": ["result"]})
    assert problem(manifest, "produced by more than one stage")


def test_consumed_kind_must_be_external_or_produced_earlier():
    manifest = valid_manifest()
    manifest["stages"][0]["consumes"] = ["missing"]
    assert problem(manifest, "consumes 'missing' before it is produced")


@pytest.mark.parametrize("required_stage,required_scope,role", [
    ("unknown", "item", "proof"),
    ("fetch", "run", "proof"),
    ("fetch", "item", "unknown"),
])
def test_requires_must_reference_item_stage_and_declared_role(required_stage, required_scope, role):
    manifest = valid_manifest()
    manifest["items"] = {"roles": ["policy", "proof"]}
    manifest["stages"][0]["scope"] = required_scope
    manifest["stages"].append({"name": "wait", "scope": "item", "consumes": [], "produces": [],
                                "requires": [{"stage": required_stage, "item_role": role}]})
    problems = validate_manifest(manifest)
    if required_stage == "unknown":
        assert any("unknown stage" in value for value in problems)
    if required_scope != "item":
        assert any("must have scope item" in value for value in problems)
    if role == "unknown":
        assert any("must be listed in items.roles" in value for value in problems)


def test_data_and_control_cycles_are_reported():
    manifest = valid_manifest()
    manifest["external_inputs"] = []
    manifest["stages"] = [
        {"name": "first", "scope": "run", "consumes": ["second_output"], "produces": ["first_output"]},
        {"name": "second", "scope": "run", "consumes": ["first_output"], "produces": ["second_output"]},
    ]
    assert problem(manifest, "contain a cycle")


def test_cycle_created_by_combining_data_and_control_edges_is_reported():
    manifest = valid_manifest()
    manifest["items"] = {"roles": ["policy", "proof"]}
    manifest["external_inputs"] = ["source"]
    manifest["evidence"]["kinds_allowed"] = []
    manifest["stages"] = [
        {"name": "consume", "scope": "item", "item_roles": ["proof"], "consumes": ["source"],
         "produces": ["facts"], "requires": [{"stage": "gate", "item_role": "policy"}]},
        {"name": "aggregate", "scope": "run", "consumes": ["facts"], "produces": ["decision"]},
        {"name": "gate", "scope": "item", "item_roles": ["policy"], "consumes": ["decision"],
         "produces": ["gate_result"]},
    ]
    assert problem(manifest, "contain a cycle")


def test_manifest_sample_control_edge_is_not_a_cycle():
    path = Path(__file__).resolve().parents[2].parent / "shared-docs" / "manifests" / "insurance-claims.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert not problem(manifest, "contain a cycle")


def test_unregistered_validator_is_reported():
    manifest = valid_manifest()
    manifest["artifacts"]["result"]["consistency"] = [
        {"id": "check", "validator": "unknown_validator", "source": "source", "fields": ["value"]}
    ]
    assert problem(manifest, "validator 'unknown_validator' is not registered")


def test_pack_validator_registry_is_supplied_by_pack_loader():
    manifest = valid_manifest()
    manifest["pack"] = "example"
    manifest["artifacts"]["result"]["consistency"] = [
        {"id": "check", "validator": "from_pack", "source": "source", "fields": ["value"]}
    ]
    assert validate_manifest(manifest, pack_validators={"from_pack"}) == []


def test_invalid_artifact_schema_is_reported():
    manifest = valid_manifest()
    manifest["artifacts"]["result"]["schema"] = {"type": "not-a-json-schema-type"}
    assert problem(manifest, "schema is invalid")


def test_evidence_kinds_must_be_produced_or_external():
    manifest = valid_manifest()
    manifest["evidence"]["level"] = "E3"
    manifest["evidence"]["kinds_allowed"] = ["unavailable"]
    problems = validate_manifest(manifest)
    assert any("evidence.level must be" in value for value in problems)
    assert any("neither produced nor external" in value for value in problems)


def test_missing_evidence_section_is_allowed_by_registration_required_key_list():
    manifest = valid_manifest()
    del manifest["evidence"]
    assert validate_manifest(manifest) == []

