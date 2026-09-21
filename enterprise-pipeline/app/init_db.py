from sqlalchemy import text
from app.database import Base, engine
from app.models import (
    Claim,
    Document,
    PolicyChunk,
    OCRResultRecord,
    ExtractionResultRecord,
    RuleEvaluationRecord,
)  # Register models with Base.metadata


def init_db():
    try:
        print("Enabling pgvector extension...")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
    except Exception as e:
        print(f"Skipping vector extension (if non-pgvector database): {e}")

    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_status VARCHAR DEFAULT 'pending';"))
            conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_result JSONB NULL;"))
            conn.commit()
    except Exception as e:
        print(f"Schema alter notice: {e}")

    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")


if __name__ == "__main__":
    init_db()
