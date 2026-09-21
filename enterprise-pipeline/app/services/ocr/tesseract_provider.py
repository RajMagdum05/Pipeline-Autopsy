import io
import os
from pathlib import Path
from typing import List, Union, Optional, Dict, Tuple
from pydantic import BaseModel, Field
from PIL import Image
import pymupdf as fitz
import pytesseract

from app.services.ocr.exceptions import (
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)
from app.services.ocr.document_loader import (
    DocumentLoader,
    ValidatedDocument,
    load_and_validate_document,
)
from app.services.ocr.image_preprocessor import PreprocessedImageResult

# Check common Windows Tesseract installation paths if environment variable is not explicitly set
_possible_paths = [
    os.getenv("TESSERACT_CMD"),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
]
for p in _possible_paths:
    if p and os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        break


class StructuredWordResult(BaseModel):
    """
    Word-level OCR result containing recognized text, confidence score, and bounding box coordinates.
    """
    text: str = Field(..., description="Recognized word text string")
    confidence: float = Field(..., description="OCR confidence score (0-100)")
    bounding_box: dict[str, float] = Field(..., description="Word bounding box dict with x0, y0, x1, y1")


class StructuredLineResult(BaseModel):
    """
    Line-level OCR result grouping constituent word results.
    """
    text: str = Field(..., description="Line text string")
    confidence: Optional[float] = Field(default=None, description="Average line confidence score")
    bounding_box: Optional[dict[str, float]] = Field(default=None, description="Line envelope bounding box")
    words: List[StructuredWordResult] = Field(default_factory=list, description="Constituent words")


class StructuredPageResult(BaseModel):
    """
    Structured OCR result for a single preprocessed page image.
    """
    document_id: Optional[Union[int, str]] = Field(default=None, description="Associated document ID")
    page_number: int = Field(..., description="1-based page index")
    image_path: str = Field(..., description="Path to source preprocessed page image")
    ocr_text: str = Field(..., description="Full recognized text string from this page")
    lines: List[StructuredLineResult] = Field(default_factory=list, description="Line-level OCR structures")
    words: List[StructuredWordResult] = Field(default_factory=list, description="Flat list of recognized words")


class StructuredDocumentOCRResult(BaseModel):
    """
    Structured document-level container for Tesseract OCR execution output.
    """
    engine: str = Field(default="tesseract", description="OCR engine name")
    document_id: Optional[Union[int, str]] = Field(default=None, description="Document database ID")
    file_name: str = Field(..., description="Base filename of the document")
    total_pages: int = Field(..., description="Total page count")
    pages: List[StructuredPageResult] = Field(default_factory=list, description="Per-page OCR results")


class TesseractPageResult(BaseModel):
    """Legacy Page-level text result for backwards compatibility."""
    page_number: int = Field(..., description="1-based page index")
    raw_text: str = Field(..., description="Recognized text from Tesseract OCR")


class TesseractOCRResult(BaseModel):
    """Legacy Structured output for backwards compatibility."""
    engine: str = Field(default="tesseract", description="Name of the OCR engine used")
    file_name: str = Field(..., description="Base filename of the document")
    total_pages: int = Field(..., description="Total page count processed")
    pages: List[TesseractPageResult] = Field(default_factory=list, description="Per-page OCR text results")


class TesseractOCRProvider:
    """
    Production-grade Tesseract OCR Provider supporting structured word-level evidence extraction.
    """

    ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

    def is_tesseract_available(self) -> bool:
        """Checks if Tesseract binary is available on the host system."""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def _verify_tesseract_installed(self) -> None:
        if not self.is_tesseract_available():
            raise DocumentProcessingError(
                "Tesseract OCR executable is not installed or not found on system PATH."
            )

    def process_image_to_structured_page(
        self,
        image_input: Union[Image.Image, str, Path],
        page_number: int = 1,
        document_id: Optional[Union[int, str]] = None,
        image_path_str: Optional[str] = None,
    ) -> StructuredPageResult:
        """
        Runs Tesseract OCR on an image and extracts structured word-level evidence.

        Args:
            image_input: PIL Image or path to image file.
            page_number: 1-based page number association.
            document_id: Optional document database ID association.
            image_path_str: Optional source image path string.

        Returns:
            StructuredPageResult: Structured word and line OCR results.
        """
        if isinstance(image_input, (str, Path)):
            img_path = Path(image_input)
            image_path_str = image_path_str or str(img_path.resolve())
            try:
                img = Image.open(img_path)
            except Exception as err:
                raise DocumentProcessingError(f"Failed to open image file '{img_path}': {str(err)}") from err
        elif isinstance(image_input, Image.Image):
            img = image_input
            image_path_str = image_path_str or "[in-memory PIL image]"
        else:
            raise DocumentProcessingError(f"Invalid image_input type: {type(image_input).__name__}")

        if not self.is_tesseract_available():
            # Return empty structured result if binary is not installed on system
            return StructuredPageResult(
                document_id=document_id,
                page_number=page_number,
                image_path=image_path_str,
                ocr_text="",
                lines=[],
                words=[],
            )

        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        except Exception as err:
            raise DocumentProcessingError(
                f"Tesseract OCR image_to_data execution failed: {str(err)}"
            ) from err

        n_boxes = len(data.get("text", []))
        line_words_map: Dict[Tuple[int, int, int], List[Dict[str, float | str]]] = {}

        for i in range(n_boxes):
            word_str = str(data["text"][i]).strip()
            conf_val = float(data["conf"][i])
            if not word_str or conf_val < 0:
                continue

            block_num = int(data["block_num"][i])
            par_num = int(data["par_num"][i])
            line_num = int(data["line_num"][i])
            key = (block_num, par_num, line_num)

            if key not in line_words_map:
                line_words_map[key] = []

            left = float(data["left"][i])
            top = float(data["top"][i])
            w_w = float(data["width"][i])
            w_h = float(data["height"][i])

            line_words_map[key].append({
                "text": word_str,
                "conf": round(conf_val, 2),
                "x0": round(left, 2),
                "y0": round(top, 2),
                "x1": round(left + w_w, 2),
                "y1": round(top + w_h, 2),
            })

        lines: List[StructuredLineResult] = []
        all_words: List[StructuredWordResult] = []
        raw_line_texts: List[str] = []

        for key, word_dicts in line_words_map.items():
            line_words: List[StructuredWordResult] = []
            for w in word_dicts:
                word_obj = StructuredWordResult(
                    text=str(w["text"]),
                    confidence=float(w["conf"]),
                    bounding_box={
                        "x0": float(w["x0"]),
                        "y0": float(w["y0"]),
                        "x1": float(w["x1"]),
                        "y1": float(w["y1"]),
                    },
                )
                line_words.append(word_obj)
                all_words.append(word_obj)

            if not line_words:
                continue

            line_str = " ".join(w.text for w in line_words).strip()
            if not line_str:
                continue

            raw_line_texts.append(line_str)
            avg_conf = round(sum(w.confidence for w in line_words) / len(line_words), 2)
            min_x0 = min(w.bounding_box["x0"] for w in line_words)
            min_y0 = min(w.bounding_box["y0"] for w in line_words)
            max_x1 = max(w.bounding_box["x1"] for w in line_words)
            max_y1 = max(w.bounding_box["y1"] for w in line_words)

            lines.append(
                StructuredLineResult(
                    text=line_str,
                    confidence=avg_conf,
                    bounding_box={"x0": min_x0, "y0": min_y0, "x1": max_x1, "y1": max_y1},
                    words=line_words,
                )
            )

        ocr_text = "\n".join(raw_line_texts)
        if not ocr_text:
            try:
                ocr_text = pytesseract.image_to_string(img).strip()
            except Exception:
                ocr_text = ""

        return StructuredPageResult(
            document_id=document_id,
            page_number=page_number,
            image_path=image_path_str,
            ocr_text=ocr_text,
            lines=lines,
            words=all_words,
        )

    def process_preprocessed_image(
        self, prep_result: PreprocessedImageResult
    ) -> StructuredPageResult:
        """
        Executes Tesseract OCR on a preprocessed page image result object.

        Args:
            prep_result: PreprocessedImageResult object.

        Returns:
            StructuredPageResult: Page-level OCR result with word-level bounding boxes and confidence.
        """
        return self.process_image_to_structured_page(
            image_input=prep_result.preprocessed_image_path,
            page_number=prep_result.page_number,
            document_id=prep_result.document_id,
            image_path_str=prep_result.preprocessed_image_path,
        )

    def process(self, document: Union[ValidatedDocument, str, Path]) -> TesseractOCRResult:
        """Processes document and returns legacy TesseractOCRResult for backwards compatibility."""
        self._verify_tesseract_installed()
        if isinstance(document, (str, Path)):
            val_doc = load_and_validate_document(document)
        else:
            val_doc = document

        res = self.process_image_to_structured_page(val_doc.file_path, page_number=1)
        return TesseractOCRResult(
            engine="tesseract",
            file_name=val_doc.file_name,
            total_pages=1,
            pages=[TesseractPageResult(page_number=1, raw_text=res.ocr_text)],
        )


def run_tesseract_ocr(document: Union[ValidatedDocument, str, Path]) -> TesseractOCRResult:
    """Convenience function to run Tesseract OCR on a document."""
    provider = TesseractOCRProvider()
    return provider.process(document)


def run_tesseract_on_preprocessed_page(
    prep_result: PreprocessedImageResult,
) -> StructuredPageResult:
    """Convenience function to run Tesseract OCR on a preprocessed page image."""
    provider = TesseractOCRProvider()
    return provider.process_preprocessed_image(prep_result)
