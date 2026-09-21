import tempfile
from pathlib import Path
import pytest

from app.services.ocr import (
    DocumentLoader,
    ValidatedDocument,
    load_and_validate_document,
    DocumentProcessingError,
    DocumentNotFoundError,
    NotAFileError,
    UnsupportedDocumentTypeError,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_valid_pdf_file(temp_dir):
    pdf_path = temp_dir / "sample_claim.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 sample content")

    loader = DocumentLoader()
    doc = loader.load_and_validate(pdf_path)

    assert isinstance(doc, ValidatedDocument)
    assert doc.file_path == pdf_path.resolve()
    assert doc.file_name == "sample_claim.pdf"
    assert doc.extension == ".pdf"
    assert doc.file_size_bytes == len(b"%PDF-1.4 sample content")


@pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"])
def test_valid_image_formats(temp_dir, ext):
    file_path = temp_dir / f"receipt{ext}"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n fake image content")

    doc = load_and_validate_document(file_path)

    assert isinstance(doc, ValidatedDocument)
    assert doc.file_name == f"receipt{ext}"
    assert doc.extension == ext.lower()
    assert doc.file_size_bytes > 0


def test_missing_file_raises_not_found(temp_dir):
    missing_path = temp_dir / "non_existent_document.pdf"

    with pytest.raises(DocumentNotFoundError) as exc_info:
        load_and_validate_document(missing_path)

    assert "Document file not found" in str(exc_info.value)
    # Ensure it is a subclass of DocumentProcessingError
    assert isinstance(exc_info.value, DocumentProcessingError)


def test_empty_path_raises_not_found():
    with pytest.raises(DocumentNotFoundError):
        load_and_validate_document("")


def test_directory_path_raises_not_a_file(temp_dir):
    sub_dir = temp_dir / "some_folder.pdf"
    sub_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(NotAFileError) as exc_info:
        load_and_validate_document(sub_dir)

    assert "not a regular file" in str(exc_info.value)
    assert isinstance(exc_info.value, DocumentProcessingError)


def test_unsupported_file_extension_raises_error(temp_dir):
    txt_path = temp_dir / "claim_notes.txt"
    txt_path.write_text("Plain text notes")

    with pytest.raises(UnsupportedDocumentTypeError) as exc_info:
        load_and_validate_document(txt_path)

    assert "Unsupported document file extension '.txt'" in str(exc_info.value)
    assert isinstance(exc_info.value, DocumentProcessingError)


def test_no_extension_raises_error(temp_dir):
    no_ext_path = temp_dir / "unnamed_file"
    no_ext_path.write_bytes(b"some content")

    with pytest.raises(UnsupportedDocumentTypeError) as exc_info:
        load_and_validate_document(no_ext_path)

    assert "has no extension" in str(exc_info.value)
    assert isinstance(exc_info.value, DocumentProcessingError)
