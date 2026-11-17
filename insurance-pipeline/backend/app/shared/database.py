import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


PROJECT_ROOT = Path(os.getenv("PIPELINE_ROOT", Path(__file__).resolve().parents[3])).resolve()
default_sqlite = (PROJECT_ROOT / "database" / "insurance_claims.db").as_posix()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{default_sqlite}")
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(database_engine=engine) -> None:
    """Apply the existing claim-table compatibility rename and create legacy tables."""
    from app.claim_document_intake import models  # noqa: F401

    inspector = inspect(database_engine)
    if inspector.has_table("claims") and not inspector.has_table("legacy_claims"):
        with database_engine.begin() as connection:
            connection.execute(text("ALTER TABLE claims RENAME TO legacy_claims"))

    if database_engine.dialect.name == "postgresql" and inspect(database_engine).has_table("legacy_claims"):
        with database_engine.begin() as connection:
            primary_key_name = connection.execute(text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'legacy_claims'::regclass AND contype = 'p'"
            )).scalar_one_or_none()
            if primary_key_name and primary_key_name != "legacy_claims_pkey":
                quoted_name = connection.dialect.identifier_preparer.quote(primary_key_name)
                connection.exec_driver_sql(
                    f"ALTER TABLE legacy_claims RENAME CONSTRAINT {quoted_name} TO legacy_claims_pkey"
                )

    # Create ORM-owned legacy tables (notably documents) before migrations that
    # add foreign keys to them. Existing tables are left untouched by create_all.
    Base.metadata.create_all(bind=database_engine)

    if database_engine.dialect.name == "postgresql":
        with database_engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        migration_dir = PROJECT_ROOT / "database" / "migrations"
        for migration_path in sorted(migration_dir.glob("*.sql")):
            migration_sql = migration_path.read_text(encoding="utf-8")
            with database_engine.begin() as connection:
                for statement in migration_sql.split(";"):
                    statement = "\n".join(
                        line for line in statement.splitlines()
                        if not line.lstrip().startswith("--")
                    ).strip()
                    if statement:
                        connection.exec_driver_sql(statement)
    elif database_engine.dialect.name == "sqlite":
        for table, column, declaration in (
            ("claims", "access_token_hash", "VARCHAR(64) NULL"),
            ("claim_documents", "version_number", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if inspect(database_engine).has_table(table):
                columns = {item["name"] for item in inspect(database_engine).get_columns(table)}
                if column not in columns:
                    with database_engine.begin() as connection:
                        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    # Preserve the legacy startup migration that made OCR fields available on
    # pre-existing documents tables without changing any established columns.
    inspector = inspect(database_engine)
    if inspector.has_table("documents"):
        columns = {column["name"] for column in inspector.get_columns("documents")}
        if database_engine.dialect.name == "sqlite":
            alter_statements = []
            if "ocr_status" not in columns:
                alter_statements.append("ALTER TABLE documents ADD COLUMN ocr_status TEXT DEFAULT 'pending'")
            if "ocr_result" not in columns:
                alter_statements.append("ALTER TABLE documents ADD COLUMN ocr_result TEXT NULL")
        else:
            alter_statements = []
            if "ocr_status" not in columns:
                alter_statements.append("ALTER TABLE documents ADD COLUMN ocr_status VARCHAR DEFAULT 'pending'")
            if "ocr_result" not in columns:
                alter_statements.append("ALTER TABLE documents ADD COLUMN ocr_result JSONB NULL")
        for statement in alter_statements:
            with database_engine.begin() as connection:
                connection.exec_driver_sql(statement)
