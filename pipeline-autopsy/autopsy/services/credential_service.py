"""
Credential Management and Cryptographic API Key Service for Pipeline Autopsy.

Handles secure key generation, SHA-256 hashing, non-retrievable storage,
and lifecycle management (creation, validation, and revocation).
"""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from autopsy.db.models import ProjectModel, ApiKeyModel


class CredentialService:
    """
    Service layer for customer projects and API key credentials.
    """

    @staticmethod
    def generate_raw_api_key() -> str:
        """Generates a cryptographically secure random API key with standard prefix."""
        random_token = secrets.token_urlsafe(32)
        return f"sk_live_{random_token}"

    @staticmethod
    def hash_api_key(raw_key: str) -> str:
        """Computes deterministic SHA-256 hex digest for storage and verification."""
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def get_key_prefix(raw_key: str) -> str:
        """Generates a safe masked prefix for display purposes only."""
        clean = raw_key.strip()
        if len(clean) > 12:
            return f"{clean[:12]}..."
        return f"{clean[:6]}..."

    def create_project(
        self,
        name: str,
        description: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> ProjectModel:
        """Creates and persists a new customer project."""
        project = ProjectModel(
            name=name.strip(),
            description=description,
            status="ACTIVE",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    def get_project(self, project_id: str, db: Session) -> Optional[ProjectModel]:
        """Retrieves a project by its unique ID."""
        return db.query(ProjectModel).filter(ProjectModel.id == project_id).first()

    def create_api_key(
        self,
        project_id: str,
        name: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Tuple[ApiKeyModel, str]:
        """
        Provisions a new API key for a project.
        Returns the ApiKeyModel (containing hash and prefix) and the raw API key ONCE.
        The raw key is never stored in the database.
        """
        project = self.get_project(project_id, db)
        if not project:
            raise ValueError(f"Project '{project_id}' does not exist.")

        raw_key = self.generate_raw_api_key()
        key_hash = self.hash_api_key(raw_key)
        key_prefix = self.get_key_prefix(raw_key)

        key_model = ApiKeyModel(
            project_id=project_id,
            name=name.strip() if name else "default-key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            status="ACTIVE",
            created_at=datetime.now(timezone.utc),
        )
        db.add(key_model)
        db.commit()
        db.refresh(key_model)
        return key_model, raw_key

    def list_api_keys(self, project_id: str, db: Session) -> List[ApiKeyModel]:
        """Lists all API key credentials for a project (metadata only, no raw keys)."""
        return (
            db.query(ApiKeyModel)
            .filter(ApiKeyModel.project_id == project_id)
            .order_by(ApiKeyModel.created_at.desc())
            .all()
        )

    def revoke_api_key(
        self,
        project_id: str,
        key_id: str,
        db: Session,
    ) -> Optional[ApiKeyModel]:
        """
        Revokes an API key. Once revoked, subsequent telemetry with this key is rejected.
        Historical telemetry associated with the project remains intact.
        """
        key_model = (
            db.query(ApiKeyModel)
            .filter(
                ApiKeyModel.id == key_id,
                ApiKeyModel.project_id == project_id,
            )
            .first()
        )
        if not key_model:
            return None

        key_model.status = "REVOKED"
        key_model.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(key_model)
        return key_model

    def validate_api_key(
        self,
        raw_key: str,
        db: Session,
    ) -> Optional[Tuple[str, ApiKeyModel]]:
        """
        Validates an incoming raw API key against database hashes.
        Returns (project_id, ApiKeyModel) if valid and ACTIVE, else None.
        """
        if not raw_key or not raw_key.strip():
            return None

        key_hash = self.hash_api_key(raw_key)
        key_model = (
            db.query(ApiKeyModel)
            .filter(
                ApiKeyModel.key_hash == key_hash,
                ApiKeyModel.status == "ACTIVE",
                ApiKeyModel.revoked_at.is_(None),
            )
            .first()
        )
        if not key_model:
            return None

        # Verify parent project is not suspended
        project = db.query(ProjectModel).filter(ProjectModel.id == key_model.project_id).first()
        if project and project.status != "ACTIVE":
            return None

        return key_model.project_id, key_model
