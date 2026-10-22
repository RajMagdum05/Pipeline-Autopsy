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
    Creates all Autopsy database tables in PostgreSQL or SQLite if they do not already exist
    and ensures schema migrations (such as project_id) are applied.
    """
    is_sqlite = str(engine.url).startswith("sqlite")
    db_name = "SQLite" if is_sqlite else "PostgreSQL"
    print(f"Creating Autopsy database tables ({db_name})...")
    Base.metadata.create_all(bind=engine)

    try:
        with engine.begin() as conn:
            if is_sqlite:
                cols_pipe = [row[1] for row in conn.execute(text("PRAGMA table_info(autopsy_pipelines);")).fetchall()]
                if "project_id" not in cols_pipe:
                    conn.execute(text("ALTER TABLE autopsy_pipelines ADD COLUMN project_id VARCHAR(255) DEFAULT 'default' NOT NULL;"))

                cols_exec = [row[1] for row in conn.execute(text("PRAGMA table_info(autopsy_executions);")).fetchall()]
                if "project_id" not in cols_exec:
                    conn.execute(text("ALTER TABLE autopsy_executions ADD COLUMN project_id VARCHAR(255) DEFAULT 'default' NOT NULL;"))
            else:
                conn.execute(text("ALTER TABLE autopsy_pipelines ADD COLUMN IF NOT EXISTS project_id VARCHAR(255) DEFAULT 'default' NOT NULL;"))
                conn.execute(text("ALTER TABLE autopsy_executions ADD COLUMN IF NOT EXISTS project_id VARCHAR(255) DEFAULT 'default' NOT NULL;"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autopsy_pipelines_project_id ON autopsy_pipelines(project_id);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autopsy_executions_project_id ON autopsy_executions(project_id);"))
    except Exception as e:
        print(f"Schema migration note: {e}")

    print("Autopsy database tables created successfully!")


if __name__ == "__main__":
    init_autopsy_db()
