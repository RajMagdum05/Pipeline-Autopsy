from sqlalchemy import text
from app.database.connection import Base, engine
from app.database.models import (
    Claim,
    Document,
    OCRResultRecord,
    ExtractionResultRecord,
    RuleEvaluationRecord,
)


def init_db():
    is_sqlite = str(engine.url).startswith("sqlite")

    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    # Migrate columns if tables pre-existed
    try:
        with engine.connect() as conn:
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
