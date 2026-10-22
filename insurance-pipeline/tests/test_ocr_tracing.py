import io
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
import pymupdf as fitz
from PIL import Image, ImageDraw
import pytesseract
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.database import Base
from app.models import Claim, Document
from app.services.ocr import process_document, DocumentNotFoundError, DocumentProcessingError
from app.telemetry import init_telemetry


def is_tesseract_installed() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.fixture
def telemetry_setup():
    """Fixture to configure OpenTelemetry with an InMemorySpanExporter for testing."""
    exporter = InMemorySpanExporter()
    provider = init_telemetry(service_name="enterprise-ocr-service-test", exporter=exporter)
    yield exporter, provider
    exporter.clear()


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        session = SessionLocal()

        claim = Claim(id=10, customer_name="Jane Doe", claim_amount=850.00, status="processing")
        session.add(claim)
        session.commit()

        yield tmp_path, session

        session.close()


def create_digital_pdf(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_test_image(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (300, 80), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(path, format="PNG")
    return path


def test_tracing_case_a_digital_pdf_pymupdf(telemetry_setup, temp_workspace):
    exporter, provider = telemetry_setup
    tmp_path, db = temp_workspace

    pdf_path = tmp_path / "digital_claim.pdf"
    create_digital_pdf(pdf_path, "PATIENT: JANE DOE MEDICAL INVOICE $850")

    doc = Document(
        id=501,
        claim_id=10,
        document_type="invoice",
        file_name="digital_claim.pdf",
        file_path=str(pdf_path.as_posix()),
        ocr_status="pending",
    )
    db.add(doc)
    db.commit()

    result = process_document(document_id=501, db=db)
    assert result.engine == "pymupdf"

    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # 1. Verify parent and child spans exist
    assert "ocr.process_document" in span_names
    assert "document.load" in span_names
    assert "document.inspect" in span_names
    assert "ocr.extract" in span_names
    assert "ocr.normalize" in span_names
    assert "ocr.persist" in span_names

    root_span = [s for s in spans if s.name == "ocr.process_document"][0]

    # 2. Verify span attributes
    assert root_span.attributes["document_id"] == 501
    assert root_span.attributes["claim_id"] == 10
    assert root_span.attributes["ocr.engine"] == "pymupdf"
    assert root_span.attributes["file_name"] == "digital_claim.pdf"
    assert root_span.attributes["file_type"] == ".pdf"
    assert root_span.attributes["processing_status"] == "success"

    # 3. Verify trace_id consistency across child spans
    trace_id = root_span.context.trace_id
    for s in spans:
        assert s.context.trace_id == trace_id

    # 4. SECURITY CHECK: Verify sensitive raw text is NOT stored in trace attributes
    for s in spans:
        for attr_key, attr_val in s.attributes.items():
            if isinstance(attr_val, str):
                assert "JANE DOE" not in attr_val
                assert "MEDICAL INVOICE" not in attr_val


def test_tracing_case_b_image_tesseract(telemetry_setup, temp_workspace):
    exporter, provider = telemetry_setup
    tmp_path, db = temp_workspace

    png_path = tmp_path / "scanned_invoice.png"
    create_test_image(png_path, "PATIENT CLAIM $850")

    doc = Document(
        id=502,
        claim_id=10,
        document_type="receipt",
        file_name="scanned_invoice.png",
        file_path=str(png_path.as_posix()),
        ocr_status="pending",
    )
    db.add(doc)
    db.commit()

    mock_tess_data = {
        "text": ["PATIENT", "CLAIM"],
        "conf": ["95.0", "98.0"],
        "left": [10, 80],
        "top": [10, 10],
        "width": [60, 50],
        "height": [20, 20],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_data", return_value=mock_tess_data):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                result = process_document(document_id=502, db=db)
    else:
        result = process_document(document_id=502, db=db)

    assert result.engine == "tesseract"

    spans = exporter.get_finished_spans()
    root_span = [s for s in spans if s.name == "ocr.process_document"][0]

    assert root_span.attributes["document_id"] == 502
    assert root_span.attributes["ocr.engine"] == "tesseract"
    assert root_span.attributes["file_type"] == ".png"


def test_tracing_error_span_recording(telemetry_setup, temp_workspace):
    exporter, provider = telemetry_setup
    _, db = temp_workspace

    with pytest.raises(DocumentNotFoundError):
        process_document(document_id=999, db=db)

    spans = exporter.get_finished_spans()
    assert len(spans) > 0

    root_span = [s for s in spans if s.name == "ocr.process_document"][0]
    assert root_span.status.status_code == trace.StatusCode.ERROR
