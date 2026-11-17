import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure enterprise-pipeline root is on sys.path
pipeline_root = Path(__file__).resolve().parents[1]
if str(pipeline_root) not in sys.path:
    sys.path.insert(0, str(pipeline_root))

# Also ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Load .env
load_dotenv(pipeline_root / ".env")
load_dotenv(repo_root / ".env")

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from app.telemetry.tracer import init_telemetry

_shared_test_exporter = InMemorySpanExporter()
init_telemetry(
    service_name="insurance-pipeline",
    exporter=_shared_test_exporter,
    use_simple_processor=True,
)


@pytest.fixture(scope="function")
def in_memory_telemetry():
    """Provides a shared in-memory span exporter cleared before and after each test."""
    _shared_test_exporter.clear()
    yield _shared_test_exporter
    _shared_test_exporter.clear()
