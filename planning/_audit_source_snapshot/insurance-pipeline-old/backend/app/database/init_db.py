from pathlib import Path

from sqlalchemy import inspect, text
from app.database.connection import Base, engine
from app.database.models import (
    Claim,
    Document,
    OCRResultRecord,
    ExtractionResultRecord,
    RuleEvaluationRecord,
)


def init_db(database_engine=engine):
    is_sqlite = str(database_engine.url).startswith("sqlite")

    # Keep all existing integer-ID pipeline claims and their dependent rows
    # intact under a stable legacy table name before creating Stage 1 claims.
    inspector = inspect(database_engine)
    if inspector.has_table("claims") and not inspector.has_table("legacy_claims"):
        with database_engine.begin() as conn:
            conn.execute(text("ALTER TABLE claims RENAME TO legacy_claims"))
    if not is_sqlite and inspect(database_engine).has_table("legacy_claims"):
        # The old primary-key index may still be named claims_pkey after a
        # table rename, which would collide with the new claims UUID key.
        with database_engine.begin() as conn:
            primary_key_name = conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'legacy_claims'::regclass AND contype = 'p'"
                )
            ).scalar_one_or_none()
            if primary_key_name and primary_key_name != "legacy_claims_pkey":
                quoted_name = conn.dialect.identifier_preparer.quote(primary_key_name)
                conn.exec_driver_sql(
                    f"ALTER TABLE legacy_claims RENAME CONSTRAINT {quoted_name} TO legacy_claims_pkey"
                )

    if not is_sqlite:
        migration_path = Path(__file__).resolve().parents[3] / "database" / "migrations" / "001_stage1_claim_storage.sql"
        migration_sql = migration_path.read_text(encoding="utf-8")
        with database_engine.begin() as conn:
            for statement in migration_sql.split(";"):
                statement = "\n".join(
                    line for line in statement.splitlines()
                    if not line.lstrip().startswith("--")
                ).strip()
                if statement:
                    conn.exec_driver_sql(statement)

    print("Creating database tables...")
    Base.metadata.create_all(bind=database_engine)

    # Migrate columns if tables pre-existed
    try:
        with database_engine.connect() as conn:
            if is_sqlite:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(documents);")).fetchall()]
                if "ocr_status" not in cols:
                    conn.execute(text("ALTER TABLE documents ADD COLUMN ocr_status TEXT DEFAULT 'pending';"))
                if "ocr_result" not in cols:
                    conn.execute(text("ALTER TABLE documents ADD COLUMN ocr_result TEXT NULL;"))
            else:
                conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_status VARCHAR DEFAULT 'pending';"))
                conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_result JSONB NULL;"))
            conn.commit()
    except Exception as e:
        print(f"Schema migration notice: {e}")

    print("Database tables initialized successfully!")


if __name__ == "__main__":
    init_db()
