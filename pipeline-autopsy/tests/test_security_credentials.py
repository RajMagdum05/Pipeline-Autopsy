"""Credential storage and revocation tests for the retained X7.2 foundation."""
import uuid

import pytest

from autopsy.db.database import SessionLocal
from autopsy.db.models import ApiKeyModel, ProjectModel
from autopsy.services.credential_service import CredentialService


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_key_is_returned_once_and_only_hash_and_prefix_are_stored(db_session):
    service = CredentialService()
    project = service.create_project(f"credentials-{uuid.uuid4().hex}", db=db_session)
    key, raw_key = service.create_api_key(project.id, "test-key", db_session)

    stored = db_session.query(ApiKeyModel).filter_by(id=key.id).one()
    assert raw_key.startswith("sk_live_")
    assert stored.key_hash == service.hash_api_key(raw_key)
    assert raw_key not in stored.key_hash and raw_key not in stored.key_prefix
    assert raw_key not in repr(service.list_api_keys(project.id, db_session))
    assert service.validate_api_key(raw_key, db_session)[0] == project.id

    service.revoke_api_key(project.id, key.id, db_session)
    assert service.validate_api_key(raw_key, db_session) is None


def test_credentials_are_project_scoped(db_session):
    service = CredentialService()
    project_a = service.create_project(f"credentials-a-{uuid.uuid4().hex}", db=db_session)
    project_b = service.create_project(f"credentials-b-{uuid.uuid4().hex}", db=db_session)
    key_a, raw_a = service.create_api_key(project_a.id, "a", db_session)

    assert service.get_project(project_a.id, db_session).id == project_a.id
    assert service.get_project(project_b.id, db_session).id == project_b.id
    assert service.revoke_api_key(project_b.id, key_a.id, db_session) is None
    assert service.validate_api_key(raw_a, db_session)[0] == project_a.id
