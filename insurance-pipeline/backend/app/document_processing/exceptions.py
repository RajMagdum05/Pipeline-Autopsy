class DocumentProcessingError(Exception):
    """Base exception for all document processing and OCR errors."""

    def __init__(self, message: str, *, error_class: str = "data", code: str | None = None):
        if error_class not in {"infra", "data", "unknown"}:
            raise ValueError("error_class must be infra, data, or unknown")
        super().__init__(message)
        self.error_class = error_class
        self.code = code


class DocumentNotFoundError(DocumentProcessingError):
    """Raised when the specified document file does not exist on disk."""
    pass


class NotAFileError(DocumentProcessingError):
    """Raised when the target path exists but is not a regular file (e.g., a directory)."""
    pass


class UnsupportedDocumentTypeError(DocumentProcessingError):
    """Raised when the document file extension is not supported for OCR processing."""
    pass
