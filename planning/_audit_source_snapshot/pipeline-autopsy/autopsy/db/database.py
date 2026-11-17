import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Load root .env file and autopsy/.env
ROOT_DIR = Path(__file__).resolve().parents[2]
AUTOPSY_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(AUTOPSY_DIR / ".env", override=False)


def _is_postgres_alive(host: str = "localhost", port: int = 5432, timeout: float = 1.0) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, int(port)))
        s.close()
        return result == 0
    except Exception:
        return False


def get_database_url() -> str:
    raw_url = os.getenv("AUTOPSY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if raw_url:
        return raw_url

    user = os.getenv("POSTGRES_USER", "pipeline")
    password = os.getenv("POSTGRES_PASSWORD", "changeme")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    db = os.getenv("POSTGRES_DB", "pipeline_autopsy")

    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def create_resilient_engine():
    configured_url = get_database_url()

    # If it's explicitly an SQLite URL, use SQLite directly
    if isinstance(configured_url, str) and configured_url.startswith("sqlite"):
        return create_engine(
            configured_url,
            connect_args={"check_same_thread": False},
        )

    # It's a PostgreSQL URL
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))

    try:
        parsed = urlparse(configured_url)
        if parsed.hostname:
            host = parsed.hostname
        if parsed.port:
            port = parsed.port
    except Exception:
        pass

    if _is_postgres_alive(host, port, timeout=1.0):
        try:
            pg_engine = create_engine(configured_url, pool_pre_ping=True)
            with pg_engine.connect() as conn:
                pass
            print(f"[*] Autopsy connected to PostgreSQL database at {host}:{port}")
            return pg_engine
        except Exception as e:
            print(f"[!] Autopsy PostgreSQL connect check failed: {e}")

    # Fallback to local SQLite if PostgreSQL is unreachable
    sqlite_path = ROOT_DIR / "autopsy.db"
    sqlite_url = f"sqlite:///{sqlite_path.as_posix()}"
    print(f"[!] PostgreSQL is offline at {host}:{port}. Autopsy using SQLite fallback ({sqlite_path.name}) for seamless demo.")
    return create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
    )


engine = create_resilient_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
