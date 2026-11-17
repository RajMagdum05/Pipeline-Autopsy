from pathlib import Path
from typing import List, Union, Optional
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

from app.pipeline_services.ocr.exceptions import DocumentProcessingError
from app.pipeline_services.ocr.page_renderer import RenderedPageImage


class PreprocessedImageResult(BaseModel):
    """
    Metadata representation of a preprocessed OCR page image.
    """
    document_id: Optional[Union[int, str]] = Field(default=None, description="Associated document ID if available")
    page_number: int = Field(..., description="1-based page number")
    original_image_path: str = Field(..., description="Path to original rendered input PNG")
    preprocessed_image_path: str = Field(..., description="Path to separate preprocessed output PNG")
    status: str = Field(default="success", description="Preprocessing status: 'success' or 'failed'")
    applied_steps: List[str] = Field(default_factory=list, description="List of applied preprocessing transformations")
    width_px: int = Field(..., description="Preprocessed image width in pixels")
    height_px: int = Field(..., description="Preprocessed image height in pixels")
    file_size_bytes: int = Field(..., description="Preprocessed image file size in bytes")


class DocumentImagePreprocessor:
    """
    Conservative Image Preprocessor for document OCR.
    
    Transforms rendered page images into OCR-optimized images (grayscale, contrast enhancement,
    noise reduction, soft binarization) while preserving fine text, tables, stamps, and signatures.
    Leaves original rendered PNG files 100% untouched.
    """

    def preprocess_rendered_page(
        self,
        rendered_image: Union[RenderedPageImage, str, Path],
        document_id: Optional[Union[int, str]] = None,
        page_number: Optional[int] = None,
        output_path: Optional[Union[str, Path]] = None,
    ) -> PreprocessedImageResult:
        """
        Applies conservative preprocessing to a rendered page image.

        Args:
            rendered_image: RenderedPageImage instance or path to a rendered PNG image.
            document_id: Optional document ID override.
            page_number: Optional page number override if passing a raw file path.
            output_path: Optional output file path override.

        Returns:
            PreprocessedImageResult: Preprocessing result metadata.
        """
        if isinstance(rendered_image, RenderedPageImage):
            orig_path = Path(rendered_image.image_path)
            doc_id = document_id or rendered_image.document_id
            pg_num = page_number or rendered_image.page_number
        elif isinstance(rendered_image, (str, Path)):
            orig_path = Path(rendered_image)
            doc_id = document_id
            pg_num = page_number or 1
        else:
            raise DocumentProcessingError(
                f"Invalid rendered_image type: {type(rendered_image).__name__}. "
                f"Expected RenderedPageImage, str, or Path."
            )

        if not orig_path.exists():
            raise DocumentProcessingError(f"Original rendered image does not exist: {orig_path}")

        # Determine target output path
        if output_path:
            target_file = Path(output_path)
        else:
            target_dir = orig_path.parent
            target_file = target_dir / f"preprocessed_page_{pg_num}.png"

        target_file.parent.mkdir(parents=True, exist_ok=True)

        applied_steps: List[str] = []

        try:
            with Image.open(orig_path) as img:
                w_px, h_px = img.size

                # 1. Grayscale Conversion
                img_proc = ImageOps.grayscale(img)
                applied_steps.append("grayscale")

                # 2. Contrast Enhancement (Autocontrast with 0.5% cutoff)
                img_proc = ImageOps.autocontrast(img_proc, cutoff=0.5)
                applied_steps.append("contrast_enhancement")

                # 3. Noise Reduction & Edge Sharpening (UnsharpMask)
                img_proc = img_proc.filter(
                    ImageFilter.UnsharpMask(radius=1.0, percent=110, threshold=3)
                )
                applied_steps.append("noise_reduction_sharpening")

                # 4. Soft Binarization / Background Noise Cleanup (Preserves stamps & signatures)
                # Maps ultra-light background artifacts (>= 250) to pure white (255)
                img_proc = img_proc.point(lambda p: 255 if p >= 250 else p)
                applied_steps.append("soft_binarization")

                # Save separate preprocessed PNG file
                img_proc.save(str(target_file), format="PNG")

            file_size = target_file.stat().st_size

            return PreprocessedImageResult(
                document_id=doc_id,
                page_number=pg_num,
                original_image_path=str(orig_path.resolve()),
                preprocessed_image_path=str(target_file.resolve()),
                status="success",
                applied_steps=applied_steps,
                width_px=w_px,
                height_px=h_px,
                file_size_bytes=file_size,
            )
        except Exception as err:
            raise DocumentProcessingError(
                f"Failed to preprocess page image '{orig_path.name}': {str(err)}"
            ) from err

    def preprocess_batch(
        self,
        rendered_images: List[RenderedPageImage],
        document_id: Optional[Union[int, str]] = None,
    ) -> List[PreprocessedImageResult]:
        """
        Preprocesses a list of RenderedPageImage objects.
        """
        results: List[PreprocessedImageResult] = []
        for item in rendered_images:
            res = self.preprocess_rendered_page(item, document_id=document_id)
            results.append(res)
        return results


def preprocess_page_image(
    rendered_image: Union[RenderedPageImage, str, Path],
    document_id: Optional[Union[int, str]] = None,
    page_number: Optional[int] = None,
) -> PreprocessedImageResult:
    """Convenience function to conservatively preprocess a rendered page image."""
    preprocessor = DocumentImagePreprocessor()
    return preprocessor.preprocess_rendered_page(
        rendered_image=rendered_image, document_id=document_id, page_number=page_number
    )
