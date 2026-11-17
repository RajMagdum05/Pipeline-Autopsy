import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from autopsy.db.database import Base, engine
from autopsy.db.models import ProjectModel, ApiKeyModel


def init_autopsy_db():
    """
    Creates the retained project and API-key tables if they do not already exist.
    """
    is_sqlite = str(engine.url).startswith("sqlite")
    db_name = "SQLite" if is_sqlite else "PostgreSQL"
    print(f"Creating Autopsy database tables ({db_name})...")
    Base.metadata.create_all(bind=engine, tables=[ProjectModel.__table__, ApiKeyModel.__table__])

    print("Autopsy database tables created successfully!")


if __name__ == "__main__":
    init_autopsy_db()
