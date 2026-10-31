import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.database import get_db
from app.models import Claim, Document
from app.schemas import DocumentResponse, OCRResult
from app.pipeline_services.ocr import (
    OCRApplicationService,
    OCRPersistenceService,
    DocumentProcessingError,
    DocumentNotFoundError,
)

router = APIRouter()
tracer = trace.get_tracer("enterprise_pipeline.documents")

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}


@router.post(
    "/claims/{claim_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    claim_id: int,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    with tracer.start_as_current_span("upload_document") as span:
        span.set_attribute("claim_id", claim_id)
        span.set_attribute("document_type", document_type)
        if file.filename:
            span.set_attribute("file_name", file.filename)

        # 1. Verify that the claim exists
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            span.set_status(Status(StatusCode.ERROR, f"Claim with id {claim_id} not found"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim with id {claim_id} not found",
            )

        # 2. Security validation: allow only PDF, PNG, JPG, JPEG
        file_ext = Path(file.filename).suffix.lower() if file.filename else ""
        if file_ext not in ALLOWED_EXTENSIONS:
            span.set_status(Status(StatusCode.ERROR, f"Unsupported file type '{file_ext}'"))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type. Allowed formats: PDF, PNG, JPG, JPEG.",
            )

        # 3. Create storage directory structure: storage/claims/{claim_id}/
        storage_dir = Path("storage") / "claims" / str(claim_id)
        storage_dir.mkdir(parents=True, exist_ok=True)

        # 4. Save file to disk
        file_path = storage_dir / Path(file.filename).name
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 5. Create Document record in PostgreSQL
        new_document = Document(
            claim_id=claim_id,
            document_type=document_type,
            file_name=file.filename,
            file_path=str(file_path.as_posix()),
            ocr_status="processing",
        )

        db.add(new_document)
        db.commit()
        db.refresh(new_document)

        # 6. Run OCR via the clean orchestrator — handles load, inspect, extract, normalize, and persist
        try:
            orchestrator = OCRApplicationService()
            ocr_result = orchestrator.process_document(document_id=new_document.id, db=db)
            # Orchestrator already sets Document.ocr_status and Document.ocr_result via persistence service
            db.refresh(new_document)
        except DocumentProcessingError as ocr_err:
            new_document.ocr_status = "failed"
            new_document.ocr_result = {
                "document_id": new_document.id,
                "status": "failed",
                "engine": "unknown",
                "errors": [str(ocr_err)],
                "pages": [],
            }
            db.commit()
            db.refresh(new_document)
        except Exception as err:
            new_document.ocr_status = "failed"
            new_document.ocr_result = {
                "document_id": new_document.id,
                "status": "failed",
                "engine": "unknown",
                "errors": [f"Unexpected error: {str(err)}"],
                "pages": [],
            }
            db.commit()
            db.refresh(new_document)

        span.set_attribute("document_id", new_document.id)
        span.set_attribute("ocr_status", new_document.ocr_status)
        span.set_status(Status(StatusCode.OK))

        # 7. Return document metadata with OCR summary
        return new_document


@router.get(
    "/claims/{claim_id}/documents",
    response_model=list[DocumentResponse],
)
def get_documents(claim_id: int, db: Session = Depends(get_db)):
    with tracer.start_as_current_span("get_documents") as span:
        span.set_attribute("claim_id", claim_id)
        # 1. Verify that the claim exists
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            span.set_status(Status(StatusCode.ERROR, f"Claim with id {claim_id} not found"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim with id {claim_id} not found",
            )

        # 2. Query and return all documents for this claim
        docs = db.query(Document).filter(Document.claim_id == claim_id).order_by(Document.id.asc()).all()
        span.set_attribute("documents_count", len(docs))
        span.set_status(Status(StatusCode.OK))
        return docs


@router.get(
    "/claims/{claim_id}/documents/{document_id}/ocr",
    response_model=OCRResult,
)
def get_document_ocr(claim_id: int, document_id: int, db: Session = Depends(get_db)):
    """
    Returns the stored normalized OCR evidence result for a specific document.
    If not yet processed, triggers OCR on demand via the clean orchestrator.
    """
    with tracer.start_as_current_span("get_document_ocr") as span:
        span.set_attribute("claim_id", claim_id)
        span.set_attribute("document_id", document_id)

        doc = db.query(Document).filter(Document.id == document_id, Document.claim_id == claim_id).first()
        if not doc:
            span.set_status(Status(StatusCode.ERROR, f"Document #{document_id} for Claim #{claim_id} not found"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document #{document_id} for Claim #{claim_id} not found",
            )

        if not doc.ocr_result:
            # Trigger on-demand OCR via the orchestrator
            try:
                orchestrator = OCRApplicationService()
                ocr_result = orchestrator.process_document(document_id=doc.id, db=db)
                db.refresh(doc)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"OCR processing failed for document #{document_id}: {str(e)}",
                )

        span.set_status(Status(StatusCode.OK))
        return doc.ocr_result


@router.get(
    "/documents/{document_id}/ocr",
    response_model=OCRResult,
)
def get_document_ocr_direct(document_id: int, db: Session = Depends(get_db)):
    """
    Direct shortcut endpoint to fetch normalized OCR evidence for any document ID.
    If not yet processed, triggers OCR on demand via the clean orchestrator.
    """
    with tracer.start_as_current_span("get_document_ocr_direct") as span:
        span.set_attribute("document_id", document_id)

        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            span.set_status(Status(StatusCode.ERROR, f"Document #{document_id} not found"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document #{document_id} not found",
            )

        if not doc.ocr_result:
            try:
                orchestrator = OCRApplicationService()
                ocr_result = orchestrator.process_document(document_id=doc.id, db=db)
                db.refresh(doc)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"OCR processing failed for document #{document_id}: {str(e)}",
                )

        span.set_status(Status(StatusCode.OK))
        return doc.ocr_result


@router.get("/claims/{claim_id}/documents/{document_id}/file")
def get_document_file(claim_id: int, document_id: int, db: Session = Depends(get_db)):
    """
    Serves the actual stored original document file for preview in the browser.
    """
    doc = db.query(Document).filter(Document.id == document_id, Document.claim_id == claim_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document #{document_id} for Claim #{claim_id} not found",
        )

    file_path = Path(doc.file_path)
    if not file_path.exists():
        # Fallback relative to insurance-pipeline root
        file_path = Path(__file__).resolve().parents[2] / doc.file_path
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Physical file for document #{document_id} not found on server",
            )

    ext = doc.file_name.lower()
    if ext.endswith(".pdf"):
        media_type = "application/pdf"
    elif ext.endswith(".png"):
        media_type = "image/png"
    elif ext.endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path.resolve()),
        media_type=media_type,
        filename=doc.file_name,
        content_disposition_type="inline",
    )


@router.get("/documents/{document_id}/file")
def get_document_file_direct(document_id: int, db: Session = Depends(get_db)):
    """
    Direct shortcut endpoint to serve the original document file.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document #{document_id} not found",
        )

    file_path = Path(doc.file_path)
    if not file_path.exists():
        file_path = Path(__file__).resolve().parents[2] / doc.file_path
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Physical file for document #{document_id} not found on server",
            )

    ext = doc.file_name.lower()
    if ext.endswith(".pdf"):
        media_type = "application/pdf"
    elif ext.endswith(".png"):
        media_type = "image/png"
    elif ext.endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path.resolve()),
        media_type=media_type,
        filename=doc.file_name,
        content_disposition_type="inline",
    )

