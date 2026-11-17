"""Adapted from the legacy validator/storage helper; files live under /storage."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
import re
from uuid import uuid4


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PROOF_DOCUMENT_TYPES = {
    "hospital_bill", "fir_accident_report", "medical_report", "discharge_summary",
    "repair_estimate", "other_supporting_document",
}
_CLAIM_ID_PATTERN = re.compile(r"^CLM-[A-F0-9]{32}$")
PROJECT_ROOT = Path(os.getenv("PIPELINE_ROOT", Path(__file__).resolve().parents[3])).resolve()
LOCAL_DOCUMENT_ROOT = PROJECT_ROOT / "storage" / "claims"


@dataclass(frozen=True)
class UploadPayload:
    original_file_name: str
    mime_type: str
    content: bytes
    document_type: str
    document_slot: int


@dataclass(frozen=True)
class StoredDocument:
    document_type: str
    document_slot: int
    original_file_name: str
    stored_file_name: str
    storage_path: str
    mime_type: str
    file_size_bytes: int
    checksum_sha256: str
    uploaded_at: datetime


class UploadValidationError(ValueError):
    pass


def validate_upload(*, file_name: str | None, mime_type: str | None, content: bytes, is_policy: bool = False) -> tuple[str, str]:
    if not file_name or not file_name.strip():
        raise UploadValidationError("A filename is required for each uploaded file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("Each file must be 10 MB or smaller.")
    if not content:
        raise UploadValidationError("Uploaded files cannot be empty.")

    extension = Path(file_name.replace("\\", "/")).suffix.lower()
    allowed = {".pdf": "application/pdf"} if is_policy else {
        ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    }
    expected_mime = allowed.get(extension)
    if expected_mime is None:
        formats = "PDF" if is_policy else "PDF, JPG, or PNG"
        raise UploadValidationError(f"File must be {formats}.")
    declared_mime = (mime_type or "").lower().split(";", 1)[0].strip()
    if declared_mime == "image/jpg":
        declared_mime = "image/jpeg"
    if declared_mime != expected_mime:
        raise UploadValidationError("File extension and MIME type do not match.")

    if expected_mime == "application/pdf":
        signature_valid = b"%PDF-" in content[:1024]
    elif expected_mime == "image/jpeg":
        signature_valid = content.startswith(b"\xff\xd8\xff")
    else:
        signature_valid = content.startswith(b"\x89PNG\r\n\x1a\n")
    if not signature_valid:
        raise UploadValidationError("File content does not match its declared document type.")
    return extension, expected_mime


def save_original_upload(claim_id: str, payload: UploadPayload) -> StoredDocument:
    if not _CLAIM_ID_PATTERN.fullmatch(claim_id):
        raise ValueError("Invalid public claim identifier for document storage.")
    claim_dir = LOCAL_DOCUMENT_ROOT / claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(payload.original_file_name.replace("\\", "/")).suffix.lower()
    stored_name = "policy_document.pdf" if payload.document_slot == 0 else f"document_{payload.document_slot}{extension}"
    destination = claim_dir / stored_name
    try:
        with destination.open("xb") as output:
            output.write(payload.content)
    except Exception:
        destination.unlink(missing_ok=True)
        try:
            claim_dir.rmdir()
        except OSError:
            pass
        raise
    return StoredDocument(
        document_type=payload.document_type,
        document_slot=payload.document_slot,
        original_file_name=payload.original_file_name,
        stored_file_name=stored_name,
        storage_path=destination.relative_to(PROJECT_ROOT).as_posix(),
        mime_type=payload.mime_type,
        file_size_bytes=len(payload.content),
        checksum_sha256=sha256(payload.content).hexdigest(),
        uploaded_at=datetime.now(timezone.utc),
    )


def save_replacement_upload(claim_id: str, document_slot: int, version_number: int, payload: UploadPayload) -> StoredDocument:
    """Save a replacement under an immutable, server-generated versioned name."""
    if not _CLAIM_ID_PATTERN.fullmatch(claim_id):
        raise ValueError("Invalid public claim identifier for document storage.")
    extension = Path(payload.original_file_name.replace("\\", "/")).suffix.lower()
    stored_name = f"document_{document_slot}_v{version_number}_{uuid4().hex}{extension}"
    claim_dir = LOCAL_DOCUMENT_ROOT / claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)
    destination = claim_dir / stored_name
    with destination.open("xb") as output:
        output.write(payload.content)
    return StoredDocument(
        document_type=payload.document_type, document_slot=document_slot,
        original_file_name=payload.original_file_name, stored_file_name=stored_name,
        storage_path=destination.relative_to(PROJECT_ROOT).as_posix(), mime_type=payload.mime_type,
        file_size_bytes=len(payload.content), checksum_sha256=sha256(payload.content).hexdigest(),
        uploaded_at=datetime.now(timezone.utc),
    )


def remove_saved_files(paths: list[str]) -> None:
    for relative_path in reversed(paths):
        target = (PROJECT_ROOT / relative_path).resolve()
        if not target.is_relative_to(LOCAL_DOCUMENT_ROOT.resolve()):
            continue
        target.unlink(missing_ok=True)
        try:
            target.parent.rmdir()
        except OSError:
            pass
