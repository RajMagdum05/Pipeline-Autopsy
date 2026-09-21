import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import text
from autopsy.db.database import Base, engine
from autopsy.db.models import (
    ProjectModel,
    ApiKeyModel,
    PipelineModel,
    ExecutionModel,
    TraceModel,
    SpanModel,
    EventModel,
    EvidenceModel,
    FailureModel,
    IncidentModel,
)


def init_autopsy_db():
    """
    Creates all Autopsy database tables in PostgreSQL if they do not already exist
    and ensures schema migrations (such as project_id) are applied.
    """
    print("Creating Autopsy database tables in PostgreSQL...")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE autopsy_pipelines ADD COLUMN IF NOT EXISTS project_id VARCHAR(255) DEFAULT 'default' NOT NULL;"))
            conn.execute(text("ALTER TABLE autopsy_executions ADD COLUMN IF NOT EXISTS project_id VARCHAR(255) DEFAULT 'default' NOT NULL;"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autopsy_pipelines_project_id ON autopsy_pipelines(project_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autopsy_executions_project_id ON autopsy_executions(project_id);"))
        except Exception as e:
            print(f"Schema migration note: {e}")

    print("Autopsy database tables created successfully!")


if __name__ == "__main__":
    init_autopsy_db()
