from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Set

from app.services.ocr.exceptions import (
    DocumentProcessingError,
    DocumentNotFoundError,
    NotAFileError,
    UnsupportedDocumentTypeError,
)


@dataclass(frozen=True)
class ValidatedDocument:
    """
    Clean internal representation of a validated document ready for OCR processing.

    Attributes:
        file_path: Absolute or resolved Path to the verified document file.
        file_name: Base filename of the document (e.g., 'claim_123.pdf').
        extension: Lowercase file extension including dot (e.g., '.pdf', '.png').
        file_size_bytes: Size of the document file in bytes.
    """
    file_path: Path
    file_name: str
    extension: str
    file_size_bytes: int


class DocumentLoader:
    """
    Production-grade Document Loader and Validator for the OCR service.

    Responsible for verifying file existence, validating that the path references
    a regular file, verifying allowed file extensions, and outputting a clean
    ValidatedDocument internal representation.
    """

    ALLOWED_EXTENSIONS: ClassVar[Set[str]] = {".pdf", ".png", ".jpg", ".jpeg"}

    def load_and_validate(self, path: str | Path) -> ValidatedDocument:
        """
        Loads and validates a document at the given file path.

        Args:
            path: Path to the stored document (string or pathlib.Path).

        Returns:
            ValidatedDocument: Validated internal representation of the document.

        Raises:
            DocumentNotFoundError: If the path does not exist.
            NotAFileError: If the path exists but is not a regular file.
            UnsupportedDocumentTypeError: If the file extension is not supported.
            DocumentProcessingError: General document validation failure.
        """
        if not path:
            raise DocumentNotFoundError("Document path cannot be empty.")

        doc_path = Path(path).resolve()

        # 1. Verify file exists
        if not doc_path.exists():
            raise DocumentNotFoundError(f"Document file not found at path: {path}")

        # 2. Verify regular file (not a directory or socket/block device)
        if not doc_path.is_file():
            raise NotAFileError(f"Specified path is not a regular file: {path}")

        # 3. Determine and normalize file extension
        extension = doc_path.suffix.lower()
        if not extension:
            raise UnsupportedDocumentTypeError(
                f"Document file has no extension: {doc_path.name}. "
                f"Allowed extensions: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )

        # 4. Validate extension against allowed formats
        if extension not in self.ALLOWED_EXTENSIONS:
            raise UnsupportedDocumentTypeError(
                f"Unsupported document file extension '{extension}'. "
                f"Allowed extensions: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )

        # 5. Extract file metadata
        try:
            file_size_bytes = doc_path.stat().st_size
        except Exception as err:
            raise DocumentProcessingError(
                f"Failed to read file status for path '{doc_path}': {err}"
            ) from err

        # 6. Return clean internal representation
        return ValidatedDocument(
            file_path=doc_path,
            file_name=doc_path.name,
            extension=extension,
            file_size_bytes=file_size_bytes,
        )


def load_and_validate_document(path: str | Path) -> ValidatedDocument:
    """
    Functional convenience entry point to load and validate a document.

    Args:
        path: Path to the document.

    Returns:
        ValidatedDocument: Validated internal document representation.
    """
    loader = DocumentLoader()
    return loader.load_and_validate(path)
