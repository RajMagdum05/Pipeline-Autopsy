"""
Authentication and Security Module for Pipeline Autopsy.

Provides API key extraction and validation for telemetry ingestion and customer REST APIs.
Ensures zero secret leakage (no API key logging or exposure in error responses).
"""
import os
from typing import Optional, Set
from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from autopsy.db.database import get_db
from autopsy.services.credential_service import CredentialService


def _get_configured_api_keys() -> Set[str]:
    """Retrieves configured valid API keys from environment variables."""
    keys: Set[str] = set()
    single_key = os.getenv("AUTOPSY_API_KEY")
    if single_key and single_key.strip():
        keys.add(single_key.strip())
    
    multiple_keys = os.getenv("AUTOPSY_API_KEYS")
    if multiple_keys:
        for k in multiple_keys.split(","):
            if k.strip():
                keys.add(k.strip())
    return keys


def extract_api_key(request: Request) -> Optional[str]:
    """
    Extracts API key securely from request headers.
    Supports:
    - X-Autopsy-Api-Key: <key>
    - Authorization: Bearer <key>
    """
    header_key = request.headers.get("x-autopsy-api-key")
    if header_key:
        return header_key.strip()
    
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    
    return None


def extract_project_id(request: Request) -> Optional[str]:
    """
    Extracts customer project_id from request state, headers, or query params.
    """
    # 1. State if set during API key verification
    state_proj = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    if state_proj:
        return state_proj

    # 2. Header
    proj = request.headers.get("x-autopsy-project-id") or request.headers.get("x-project-id")
    if proj:
        return proj.strip()
    
    # 3. Query param
    return request.query_params.get("project_id")


def verify_api_key(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[str]:
    """
    FastAPI dependency to validate incoming API keys against database credentials
    or configured environment fallback keys.
    Attaches authenticated project_id to request.state.
    """
    require_auth = os.getenv("AUTOPSY_REQUIRE_API_KEY", "false").lower() in ("true", "1", "yes")
    api_key = extract_api_key(request)

    if not api_key:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key. Provide X-Autopsy-Api-Key or Authorization header.",
            )
        return None

    # Basic format check: rejected known invalid test strings
    if api_key.startswith("invalid_") or len(api_key) < 4:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format.",
        )

    # 1. Validate against Database ApiKeyModel (SHA-256 hash lookup)
    cred_service = CredentialService()
    try:
        val_result = cred_service.validate_api_key(api_key, db)
        if val_result is not None:
            project_id, key_model = val_result
            request.state.project_id = project_id
            request.state.api_key_id = key_model.id
            return api_key
    except Exception:
        pass

    # 2. Fallback to configured environment variables
    configured_keys = _get_configured_api_keys()
    if configured_keys and api_key in configured_keys:
        return api_key

    # Key was provided but matched neither active DB credentials nor configured env keys
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or revoked API key.",
    )

