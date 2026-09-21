import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Load root .env file for PostgreSQL settings
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(".env")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_database_url() -> str | URL:
    if os.getenv("AUTOPSY_DATABASE_URL"):
        return os.getenv("AUTOPSY_DATABASE_URL")
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")

    return URL.create(
        drivername="postgresql+psycopg",
        username=_required_env("POSTGRES_USER"),
        password=_required_env("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=_required_env("POSTGRES_DB"),
    )


db_url = get_database_url()
engine_args = {}
if isinstance(db_url, str) and db_url.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}

engine = create_engine(db_url, **engine_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
