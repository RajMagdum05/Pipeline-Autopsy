import base64
import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient

from autopsy.core.contract import artifact_id
from autopsy.db.database import SessionLocal
from autopsy.db.models import ExecutionRecord
from autopsy.main import app


HEADERS = {"X-Autopsy-Api-Key": "autopsy-test-static-key"}


@pytest.fixture
def artifact_context(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_BLOB_DIR", str(tmp_path / "blobs"))
    suffix = uuid.uuid4().hex[:8]
    pipeline_name = f"artifact_test_{suffix}"
    execution_id = f"execution-{suffix}"
    manifest = {
        "manifest": "pipeline-manifest/1",
        "pipeline": pipeline_name,
        "version": "1.0.0",
        "evidence": {"level": "E2", "kinds_allowed": ["page_text"], "retention_days": 3},
        "external_inputs": ["source"],
        "stages": [{"name": "read", "scope": "run", "consumes": ["source"], "produces": ["page_text"]}],
    }
    with TestClient(app, headers=HEADERS) as client:
        registration = client.put(
            f"/v1/pipelines/{pipeline_name}/versions/1.0.0", json=manifest, headers=HEADERS
        )
        assert registration.status_code == 200, registration.text
        with SessionLocal() as db:
            db.add(ExecutionRecord(
                id=execution_id, project_id="default", pipeline=pipeline_name,
                version="1.0.0", trace_ids=[], status="receiving",
            ))
            db.commit()
        yield client, manifest, execution_id
        with SessionLocal() as db:
            execution = db.get(ExecutionRecord, execution_id)
            if execution is not None:
                db.delete(execution)
            db.commit()


def _payload(manifest, execution_id, content, *, kind="page_text", redacted=False, item_id=""):
    return {
        "id": artifact_id(content, kind, execution_id, item_id),
        "execution_id": execution_id,
        "pipeline": manifest["pipeline"],
        "version": manifest["version"],
        "stage": "read",
        "item_id": item_id,
        "kind": kind,
        "content_type": "text/plain",
        "content": content,
        "redacted": redacted,
        "redaction": "excerpt" if redacted else None,
    }


def test_upload_duplicate_and_get_round_trip_with_pii_mask(artifact_context):
    client, manifest, execution_id = artifact_context
    content = "Contact a.person@example.com at +1 (415) 555-0199, account 123456789012."
    payload = _payload(manifest, execution_id, content, item_id="item-a")
    created = client.post("/v1/artifacts", json=payload, headers=HEADERS)
    assert created.status_code == 201, created.text
    assert created.json()["sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert "[REDACTED]" in created.json()["content"]

    duplicate = client.post("/v1/artifacts", json=payload, headers=HEADERS)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    fetched = client.get(f"/v1/artifacts/{payload['id']}", headers=HEADERS)
    assert fetched.status_code == 200
    assert fetched.json()["execution_id"] == execution_id
    assert "a.person@example.com" not in fetched.json()["content"]
    assert "123456789012" not in fetched.json()["content"]


def test_redacted_content_accepts_original_content_id(artifact_context):
    client, manifest, execution_id = artifact_context
    excerpt = "Policy holder: [REDACTED]"
    payload = _payload(manifest, execution_id, excerpt, redacted=True)
    payload["id"] = "art_0123456789abcdef"
    response = client.post("/v1/artifacts", json=payload, headers=HEADERS)
    assert response.status_code == 201, response.text
    fetched = client.get(f"/v1/artifacts/{payload['id']}", headers=HEADERS)
    assert fetched.status_code == 200
    assert fetched.json()["content"] == excerpt


def test_content_b64_is_saved_and_returned_for_binary(artifact_context):
    client, manifest, execution_id = artifact_context
    raw = b"\x00\x01binary\xff"
    payload = _payload(manifest, execution_id, raw, redacted=True)
    payload["id"] = "art_abcdef0123456789"
    payload["content_type"] = "application/octet-stream"
    payload.pop("content")
    payload["content_b64"] = base64.b64encode(raw).decode("ascii")
    response = client.post("/v1/artifacts", json=payload, headers=HEADERS)
    assert response.status_code == 201, response.text
    fetched = client.get(f"/v1/artifacts/{payload['id']}", headers=HEADERS)
    assert base64.b64decode(fetched.json()["content_b64"]) == raw


@pytest.mark.parametrize("bad_id", ["bad", "art_0123456789abcdeZ"])
def test_bad_id_format_is_rejected(artifact_context, bad_id):
    client, manifest, execution_id = artifact_context
    payload = _payload(manifest, execution_id, "hello")
    payload["id"] = bad_id
    assert client.post("/v1/artifacts", json=payload, headers=HEADERS).status_code == 422


def test_unredacted_id_mismatch_is_rejected(artifact_context):
    client, manifest, execution_id = artifact_context
    payload = _payload(manifest, execution_id, "actual")
    payload["content"] = "tampered"
    assert client.post("/v1/artifacts", json=payload, headers=HEADERS).status_code == 422


def test_content_over_five_mib_is_rejected(artifact_context):
    client, manifest, execution_id = artifact_context
    content = "x" * (5 * 1024 * 1024 + 1)
    payload = _payload(manifest, execution_id, content, redacted=True)
    payload["id"] = "art_0123456789abcdef"
    assert client.post("/v1/artifacts", json=payload, headers=HEADERS).status_code == 413


def test_unknown_kind_and_non_e2_pipeline_are_forbidden(artifact_context):
    client, manifest, execution_id = artifact_context
    unknown = _payload(manifest, execution_id, "hello", kind="unlisted")
    assert client.post("/v1/artifacts", json=unknown, headers=HEADERS).status_code == 403

    manifest["pipeline"] = f"e1_{manifest['pipeline']}"
    manifest["evidence"]["level"] = "E1"
    registered = client.put(f"/v1/pipelines/{manifest['pipeline']}/versions/1.0.0", json=manifest, headers=HEADERS)
    assert registered.status_code == 200
    with SessionLocal() as db:
        db.add(ExecutionRecord(
            id=f"{execution_id}-e1", project_id="default", pipeline=manifest["pipeline"],
            version="1.0.0", trace_ids=[], status="receiving",
        ))
        db.commit()
    e1_payload = _payload(manifest, f"{execution_id}-e1", "hello")
    try:
        assert client.post("/v1/artifacts", json=e1_payload, headers=HEADERS).status_code == 403
    finally:
        with SessionLocal() as db:
            row = db.get(ExecutionRecord, f"{execution_id}-e1")
            if row:
                db.delete(row)
            db.commit()


def test_unknown_artifact_is_not_found_and_bad_get_id_is_unprocessable(artifact_context):
    client, _, _ = artifact_context
    assert client.get("/v1/artifacts/bad", headers=HEADERS).status_code == 422
    assert client.get("/v1/artifacts/art_0000000000000000", headers=HEADERS).status_code == 404
