"""
Configuration module for Pipeline Autopsy SDK.

Supports programmatic configuration and environment variable fallbacks.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AutopsyConfig:
    """
    Configuration options for Autopsy SDK.

    Attributes:
        api_key: Customer API key for authenticating with Autopsy.
        endpoint: Base URL of the Autopsy backend (e.g., http://localhost:8000).
        project_id: Unique project identifier for multi-tenant isolation.
        service_name: Name of the customer microservice or pipeline.
        environment: Deployment environment (production, staging, development).
        batch_export: Whether to use background BatchSpanProcessor (True) or SimpleSpanProcessor (False).
        timeout_seconds: Network export timeout in seconds.
        debug: Enable verbose debug logging.
    """
    api_key: str = field(default_factory=lambda: os.getenv("AUTOPSY_API_KEY", ""))
    endpoint: str = field(default_factory=lambda: os.getenv("AUTOPSY_ENDPOINT", "http://localhost:8000"))
    project_id: str = field(default_factory=lambda: os.getenv("AUTOPSY_PROJECT_ID", "default_project"))
    service_name: str = field(default_factory=lambda: os.getenv("AUTOPSY_SERVICE_NAME", "customer_service"))
    environment: str = field(default_factory=lambda: os.getenv("AUTOPSY_ENVIRONMENT", "production"))
    batch_export: bool = False
    timeout_seconds: float = 5.0
    debug: bool = False

    def get_otlp_endpoint(self) -> str:
        """Returns the full normalized OTLP HTTP trace endpoint."""
        base = self.endpoint.rstrip("/")
        if not base.endswith("/v1/traces"):
            return f"{base}/v1/traces"
        return base
