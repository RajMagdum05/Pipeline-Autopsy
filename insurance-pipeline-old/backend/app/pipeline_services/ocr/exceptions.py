class DocumentProcessingError(Exception):
    """Base exception for all document processing and OCR errors."""
    pass


class DocumentNotFoundError(DocumentProcessingError):
    """Raised when the specified document file does not exist on disk."""
    pass


class NotAFileError(DocumentProcessingError):
    """Raised when the target path exists but is not a regular file (e.g., a directory)."""
    pass


class UnsupportedDocumentTypeError(DocumentProcessingError):
    """Raised when the document file extension is not supported for OCR processing."""
    pass
