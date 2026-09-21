from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
import uuid


class Pipeline(BaseModel):
    """
    Logical pipeline or workflow definition being observed.

    Generic across AI, ML, agentic, microservice, or ETL systems.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier for the pipeline")
    name: str = Field(..., min_length=1, description="Human-readable pipeline name")
    description: Optional[str] = Field(default=None, description="Detailed purpose of the workflow")
    version: Optional[str] = Field(default="1.0.0", description="Semantic or deployment version")
    tags: List[str] = Field(default_factory=list, description="Categorization tags (e.g., ['llm', 'rag', 'etl'])")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Generic extensible metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last update timestamp")
