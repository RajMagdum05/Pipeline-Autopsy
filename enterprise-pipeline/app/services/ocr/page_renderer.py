from pathlib import Path
from typing import List, Union, Optional
from pydantic import BaseModel, Field
import pymupdf as fitz

from app.services.ocr.exceptions import DocumentProcessingError, UnsupportedDocumentTypeError
from app.services.ocr.document_loader import ValidatedDocument, load_and_validate_document
from app.services.ocr.pdf_inspector import PDFInspector, PDFInspectionResult, PDFPageInspection


class RenderedPageImage(BaseModel):
    """
    Metadata representation of an intermediate rendered PDF page image.
    """
    document_id: Optional[Union[int, str]] = Field(default=None, description="Associated document ID if available")
    page_number: int = Field(..., description="1-based page number")
    image_path: str = Field(..., description="Absolute path to stored rendered PNG image")
    width_px: int = Field(..., description="Image width in pixels")
    height_px: int = Field(..., description="Image height in pixels")
    dpi: int = Field(..., description="Rendering resolution in DPI")
    file_size_bytes: int = Field(..., description="Rendered image file size in bytes")
    rendering_engine: str = Field(default="pymupdf", description="Rendering engine used")


class PDFPageRenderer:
    """
    Renders PDF pages marked as OCR_REQUIRED into high-resolution intermediate PNG images.
    
    Preserves document structure, page numbers, full uncropped page bounds,
    and correct rotation while guaranteeing zero mutation of the original PDF file.
    """

    DEFAULT_DPI: int = 300
    DEFAULT_STORAGE_ROOT: Path = Path(r"r:\Pipeline_Autopsy\enterprise-pipeline\storage\artifacts\ocr_pages")

    def __init__(self, storage_root: Optional[Path] = None):
        self.storage_root = Path(storage_root) if storage_root else self.DEFAULT_STORAGE_ROOT
        self.inspector = PDFInspector()

    def render_ocr_required_pages(
        self,
        document: Union[ValidatedDocument, str, Path],
        document_id: Optional[Union[int, str]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        dpi: int = DEFAULT_DPI,
    ) -> List[RenderedPageImage]:
        """
        Inspects PDF and renders all pages marked as OCR_REQUIRED into high-resolution PNG images.

        Args:
            document: ValidatedDocument instance or path string/Path to a PDF file.
            document_id: Optional database document ID for tracking and output pathing.
            output_dir: Custom output directory for rendered page images.
            dpi: Rendering resolution in dots per inch (default 300 DPI).

        Returns:
            List[RenderedPageImage]: List of rendered image metadata objects for OCR_REQUIRED pages.
        """
        if isinstance(document, (str, Path)):
            validated_doc = load_and_validate_document(document)
        elif isinstance(document, ValidatedDocument):
            validated_doc = document
        else:
            raise DocumentProcessingError(
                f"Invalid document type: {type(document).__name__}. Expected ValidatedDocument, str, or Path."
            )

        if validated_doc.extension.lower() != ".pdf":
            raise UnsupportedDocumentTypeError(
                f"PDFPageRenderer only processes '.pdf' files, but received '{validated_doc.extension}'"
            )

        inspection: PDFInspectionResult = self.inspector.inspect(validated_doc, document_id=document_id)

        # Determine target output directory
        doc_folder_name = f"doc_{document_id}" if document_id else validated_doc.file_path.stem
        target_dir = Path(output_dir) if output_dir else (self.storage_root / doc_folder_name)
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            file_bytes = validated_doc.file_path.read_bytes()
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as err:
            raise DocumentProcessingError(
                f"Failed to open PDF file '{validated_doc.file_name}' for rendering: {str(err)}"
            ) from err

        try:
            rendered_images: List[RenderedPageImage] = []

            for page_info in inspection.pages:
                if page_info.status != "OCR_REQUIRED":
                    continue

                page_idx = page_info.page_number - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue

                page = doc[page_idx]
                pix = page.get_pixmap(dpi=dpi)

                image_filename = f"page_{page_info.page_number}.png"
                image_filepath = target_dir / image_filename

                pix.save(str(image_filepath))

                file_size = image_filepath.stat().st_size

                rendered_images.append(
                    RenderedPageImage(
                        document_id=document_id or inspection.document_id,
                        page_number=page_info.page_number,
                        image_path=str(image_filepath.resolve()),
                        width_px=pix.width,
                        height_px=pix.height,
                        dpi=dpi,
                        file_size_bytes=file_size,
                    )
                )

            return rendered_images
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def render_ocr_required_pages(
    document: Union[ValidatedDocument, str, Path],
    document_id: Optional[Union[int, str]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    dpi: int = 300,
) -> List[RenderedPageImage]:
    """Convenience function to render all OCR_REQUIRED pages of a PDF into PNG page images."""
    renderer = PDFPageRenderer()
    return renderer.render_ocr_required_pages(
        document=document, document_id=document_id, output_dir=output_dir, dpi=dpi
    )
