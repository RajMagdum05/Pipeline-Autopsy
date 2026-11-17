import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Load root .env file and autopsy/.env
ROOT_DIR = Path(__file__).resolve().parents[2]
AUTOPSY_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(AUTOPSY_DIR / ".env", override=False)


def get_database_url() -> str:
    raw_url = os.getenv("AUTOPSY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not raw_url or not raw_url.strip():
        raise RuntimeError("AUTOPSY_DATABASE_URL (or DATABASE_URL) must be configured")
    return raw_url.strip()


def create_resilient_engine():
    configured_url = get_database_url()

    # If it's explicitly an SQLite URL, use SQLite directly
    if isinstance(configured_url, str) and configured_url.startswith("sqlite"):
        return create_engine(
            configured_url,
            connect_args={"check_same_thread": False},
        )

    # Let the application lifespan validate the connection. Never probe sockets or
    # silently change the configured database to a different storage backend.
    return create_engine(configured_url, pool_pre_ping=True)


engine = create_resilient_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
