"""Policy-first claim document extraction with durable run and page artifacts."""
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
from uuid import UUID

import autopsy_sdk as autopsy
from app import faults
from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.claim_document_intake import storage as intake_storage
from app.claim_document_intake.models import Claim, ClaimDocument, Document, IntakeClaim
from app.document_processing.document_loader import DocumentLoader
from app.document_processing.evidence_extractor import OCREvidenceExtractor
from app.document_processing.exceptions import DocumentProcessingError
from app.document_processing.models import ProcessedDocument, ProcessedPage, ProcessingRun
from app.document_processing.normalizer import OCRNormalizer
from app.document_processing.quality_validator import OCRValidationConfig
from app.document_processing.schemas import ProcessClaimResponse
from app.information_extraction.content_service import (
    DocumentContentService, EXTRACTION_PROMPT_VERSION, EXTRACTION_VALIDATOR_VERSION,
    GEMINI_SCHEMA_ADAPTER_VERSION,
)

PROOF_TYPES = {"hospital_bill", "fir_accident_report", "medical_report", "discharge_summary", "repair_estimate", "other_supporting_document"}
QUALITY_GATE_VERSION = "ocr-quality-v2"


def _now():
    return datetime.now(timezone.utc)


class ClaimDocumentProcessingService:
    def __init__(self):
        self.loader = DocumentLoader()
        self.extractor = OCREvidenceExtractor()
        self.quality_config = OCRValidationConfig(
            min_character_count=int(os.getenv("OCR_QUALITY_MIN_CHARACTERS", "15")),
            min_word_count=int(os.getenv("OCR_QUALITY_MIN_WORDS", "3")),
            min_avg_confidence_pass=float(os.getenv("OCR_CONFIDENCE_PASS", "60")),
            min_avg_confidence_warning=float(os.getenv("OCR_CONFIDENCE_RETRY", "35")),
            low_confidence_cutoff=float(os.getenv("OCR_LOW_CONFIDENCE_CUTOFF", "60")),
            max_low_confidence_ratio=float(os.getenv("OCR_MAX_LOW_CONFIDENCE_RATIO", "0.5")),
            max_suspicious_char_ratio=float(os.getenv("OCR_MAX_SUSPICIOUS_CHAR_RATIO", "0.02")),
        )
        self.normalizer = OCRNormalizer(self.quality_config)
        self.content_service = DocumentContentService()

    def _documents_for_claim(self, db: Session, claim_id: str):
        claim = db.query(IntakeClaim).filter_by(claim_id=claim_id).one_or_none()
        if claim is None or claim.legacy_id is None:
            raise DocumentProcessingError("Claim was not found or has no linked legacy claim record.")
        legacy_claim = db.query(Claim).filter_by(id=claim.legacy_id).one_or_none()
        if legacy_claim is None:
            raise DocumentProcessingError("Claim association is incomplete; contact an administrator.")
        intake_docs = db.query(ClaimDocument).filter_by(claim_id=claim_id).order_by(ClaimDocument.document_slot).all()
        stored_docs = db.query(Document).filter_by(claim_id=legacy_claim.id).order_by(Document.id).all()
        by_storage = {}
        for intake_doc in intake_docs:
            if not intake_doc.storage_path or not intake_doc.document_type:
                raise DocumentProcessingError("A stored document is missing its role or storage reference.")
            path = (intake_storage.PROJECT_ROOT / intake_doc.storage_path).resolve()
            by_storage.setdefault(path, []).append(intake_doc)
        resolved = []
        for stored in stored_docs:
            path = Path(stored.file_path).resolve() if stored.file_path else None
            matches = by_storage.get(path, [])
            if len(matches) != 1:
                raise DocumentProcessingError("Document-to-claim association is ambiguous or missing.")
            intake_doc = matches[0]
            if stored.document_type != intake_doc.document_type:
                raise DocumentProcessingError("Document role metadata does not match across claim records.")
            resolved.append((stored, intake_doc, path, intake_doc.document_type))
        if len(resolved) != len(intake_docs):
            raise DocumentProcessingError("Some claim document records have no matching stored document row.")
        policies = [item for item in resolved if item[3] == "policy_document"]
        proofs = [item for item in resolved if item[3] in PROOF_TYPES]
        if any(item[3] != "policy_document" and item[3] not in PROOF_TYPES for item in resolved):
            raise DocumentProcessingError("A claim document has an unsupported or unresolved role.")
        if len(policies) != 1:
            raise DocumentProcessingError("Exactly one policy_document role is required; verify the claim upload metadata.")
        if not proofs:
            raise DocumentProcessingError("No supporting proof documents have a recognized persisted role.")
        return policies[0], sorted(proofs, key=lambda item: (item[1].document_slot, str(item[1].id)))

    def _validate_file(self, item):
        stored, intake_doc, path, role = item
        if not path.is_relative_to(intake_storage.LOCAL_DOCUMENT_ROOT.resolve()):
            raise DocumentProcessingError("Stored document resolves outside the permitted claims storage directory.")
        if not path.exists() or not path.is_file():
            raise DocumentProcessingError("Stored document file is missing or is not a regular file.")
        max_bytes = int(os.getenv("DOCUMENT_MAX_BYTES", str(10 * 1024 * 1024)))
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            raise DocumentProcessingError("Stored document is empty or exceeds DOCUMENT_MAX_BYTES.")
        if intake_doc.file_size_bytes is not None and size != intake_doc.file_size_bytes:
            raise DocumentProcessingError("Stored document size differs from its intake metadata.")
        digest = sha256(path.read_bytes()).hexdigest()
        if intake_doc.checksum_sha256 and digest != intake_doc.checksum_sha256:
            raise DocumentProcessingError("Stored document checksum differs from its intake metadata.")
        validated = self.loader.load_and_validate(path)
        declared_mime = (intake_doc.mime_type or "").split(";", 1)[0].strip().lower()
        expected_mime = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(validated.extension)
        if expected_mime is None or (declared_mime and declared_mime != expected_mime):
            raise DocumentProcessingError("Stored file format does not match its persisted MIME metadata.")
        if role == "policy_document" and validated.extension != ".pdf":
            raise DocumentProcessingError("The persisted policy_document must be a PDF.")
        max_pages = int(os.getenv("DOCUMENT_MAX_PAGES", "100"))
        max_pixels = int(os.getenv("DOCUMENT_MAX_RENDER_PIXELS", "30000000"))
        if validated.extension == ".pdf":
            import pymupdf
            pdf = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
            try:
                if pdf.needs_pass:
                    raise DocumentProcessingError("PDF is password-protected and cannot be processed.")
                if len(pdf) == 0:
                    raise DocumentProcessingError("PDF contains zero pages.")
                if len(pdf) > max_pages:
                    raise DocumentProcessingError("PDF exceeds DOCUMENT_MAX_PAGES.")
                dpi = int(os.getenv("OCR_RENDER_DPI", "200"))
                for page in pdf:
                    if (page.rect.width * dpi / 72) * (page.rect.height * dpi / 72) > max_pixels:
                        raise DocumentProcessingError("PDF page exceeds DOCUMENT_MAX_RENDER_PIXELS at configured OCR_RENDER_DPI.")
            finally:
                pdf.close()
        else:
            if max_pages < 1:
                raise DocumentProcessingError("Image exceeds DOCUMENT_MAX_PAGES.")
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                if image.width * image.height > max_pixels:
                    raise DocumentProcessingError("Image exceeds DOCUMENT_MAX_RENDER_PIXELS.")
        return digest, validated

    def _check_ocr(self, validated):
        needs_ocr = validated.extension != ".pdf"
        if not needs_ocr:
            import pymupdf
            with pymupdf.open(validated.file_path) as pdf:
                for page in pdf:
                    text = page.get_text().strip()
                    if len(text) < int(os.getenv("OCR_NATIVE_MIN_CHARS", "24")) or len(text.split()) < int(os.getenv("OCR_NATIVE_MIN_WORDS", "4")) or page.get_images(full=True):
                        needs_ocr = True
                        break
        if needs_ocr:
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                languages = set(pytesseract.get_languages(config=""))
                requested = os.getenv("TESSERACT_LANGUAGE", "eng").split("+")
                missing = [language for language in requested if language not in languages]
                if missing:
                    raise DocumentProcessingError(
                        "Required Tesseract language data is unavailable.",
                        error_class="infra", code="OCR_RUNTIME_UNAVAILABLE",
                    )
            except DocumentProcessingError:
                raise
            except Exception as exc:
                raise DocumentProcessingError(
                    "Tesseract OCR executable or language data is unavailable.",
                    error_class="infra", code="OCR_RUNTIME_UNAVAILABLE",
                ) from exc

    def _record_blocked_proofs(self, db, run, claim_id, proofs, failed_ids, config_version):
        for stored, intake_doc, _, role in proofs:
            db.add(ProcessedDocument(run_id=run.id, document_id=stored.id,
                intake_document_id=intake_doc.id, claim_id=claim_id, role=role,
                checksum_sha256=intake_doc.checksum_sha256, status="BLOCKED", disposition="BLOCKED",
                completed_at=_now(), error="Policy extraction gate failed; proof processing was not started.",
                configuration={"config_version": config_version}))
            failed_ids.append(str(intake_doc.id))
        db.flush()

    def _persist_quality_attempt(self, db, processed, normalized, *, retry_exhausted: bool):
        validation = normalized.processing_metadata["validation"]
        page_quality = {int(row["page_number"]): row for row in validation["page_validations"]}
        retries = []
        attempt_reasons = []
        for page in normalized.pages:
            q = page_quality.get(page.page_number, {})
            disposition = q.get("disposition", "FAILED")
            reasons = list(q.get("reasons", []))
            if disposition == "RETRY_REQUIRED":
                if retry_exhausted:
                    disposition = "HUMAN_REVIEW_REQUIRED"
                    exhaustion_reason = "The configured OCR retry limit was reached; human review is required."
                    reasons.append(exhaustion_reason)
                    attempt_reasons.append(f"Page {page.page_number}: {exhaustion_reason}")
                else:
                    retries.append(page.page_number)
            method = page.extraction_method
            engine = "pymupdf" if method == "DIRECT_TEXT" else "tesseract" if method == "TESSERACT_OCR" else "pymupdf+tesseract"
            if method == "BLANK":
                engine = "none"
            if method == "DIRECT_TEXT":
                import pymupdf
                page_engine_version = str(pymupdf.VersionBind)
            elif method in {"TESSERACT_OCR", "HYBRID"}:
                try:
                    import pytesseract
                    tesseract_version = str(pytesseract.get_tesseract_version())
                except Exception:
                    tesseract_version = "unavailable"
                page_engine_version = tesseract_version
                if method == "HYBRID":
                    page_engine_version = f"PyMuPDF {__import__('pymupdf').VersionBind}; Tesseract {tesseract_version}"
            else:
                page_engine_version = None
            page_status = "BLANK" if page.status == "BLANK" else "COMPLETED" if disposition == "ACCEPTED" else "RETRY_REQUIRED" if disposition == "RETRY_REQUIRED" else "REVIEW_REQUIRED" if disposition == "HUMAN_REVIEW_REQUIRED" else "FAILED"
            db.add(ProcessedPage(
                processed_document_id=processed.id, page_number=page.page_number,
                status=page_status, quality_status=q.get("status", "UNKNOWN"), extraction_method=method, engine=engine,
                engine_version=page_engine_version, started_at=processed.started_at or _now(), completed_at=_now(),
                disposition=disposition, confidence_score=q.get("confidence_score"),
                confidence_source=q.get("confidence_source"), confidence_scale=q.get("confidence_scale"),
                confidence_aggregation_method=q.get("aggregation_method"),
                confidence_word_count=q.get("confidence_word_count", 0),
                confidence_missing_word_count=q.get("confidence_missing_word_count", 0),
                confidence_coverage=q.get("confidence_coverage"),
                low_confidence_word_count=q.get("low_confidence_word_count", 0),
                low_confidence_word_proportion=q.get("low_confidence_word_proportion"),
                quality_metrics=q.get("quality_metrics", {}), validation_reasons=reasons,
                raw_text=page.raw_text, layout={"width": page.width, "height": page.height,
                    "status": page.status, "lines": [line.model_dump() for line in page.lines]},
                error=page.error,
            ))
        nonblank = [row for row in page_quality.values() if row.get("status") != "BLANK"]
        dispositions = [row.get("disposition") for row in nonblank]
        if not nonblank:
            disposition = "HUMAN_REVIEW_REQUIRED"
        elif retries and not retry_exhausted:
            disposition = "RETRY_REQUIRED"
        elif retry_exhausted and "RETRY_REQUIRED" in dispositions:
            disposition = "HUMAN_REVIEW_REQUIRED"
        elif "HUMAN_REVIEW_REQUIRED" in dispositions:
            disposition = "HUMAN_REVIEW_REQUIRED"
        elif all(value == "ACCEPTED" for value in dispositions):
            disposition = "ACCEPTED"
        else:
            disposition = "FAILED"
        processed.quality_status = validation.get("overall_status", "UNKNOWN")
        processed.disposition = disposition
        processed.confidence_score = validation.get("avg_document_confidence")
        processed.confidence_source = "pytesseract.image_to_data TSV word confidence" if validation.get("confidence_word_count") else "unavailable for native text or absent OCR tokens"
        processed.confidence_scale = "0-100 Tesseract score; not a probability" if validation.get("confidence_word_count") else None
        processed.confidence_aggregation_method = validation.get("aggregation_method")
        processed.confidence_word_count = validation.get("confidence_word_count", 0)
        processed.confidence_missing_word_count = validation.get("confidence_missing_word_count", 0)
        processed.confidence_coverage = validation.get("confidence_coverage")
        processed.low_confidence_word_count = validation.get("low_confidence_word_count", 0)
        processed.low_confidence_word_proportion = validation.get("low_confidence_word_proportion")
        processed.quality_metrics = {"page_count": len(normalized.pages),
            "nonblank_page_count": len(nonblank),
            "failed_page_count": sum(1 for row in nonblank if row.get("status") == "FAIL"),
            "warning_page_count": sum(1 for row in nonblank if row.get("status") == "WARNING"),
            "character_count": sum(row.get("character_count", 0) for row in page_quality.values()),
            "word_count": sum(row.get("word_count", 0) for row in page_quality.values())}
        processed.validation_reasons = [f"Page {page_number}: {reason}"
            for page_number, q in page_quality.items() for reason in q.get("reasons", [])]
        processed.validation_reasons.extend(attempt_reasons)
        processed.engine = normalized.engine
        processed.engine_version = normalized.engine_version
        processed.status = "COMPLETED" if disposition == "ACCEPTED" else "RETRY_REQUIRED" if disposition == "RETRY_REQUIRED" else "REVIEW_REQUIRED" if disposition == "HUMAN_REVIEW_REQUIRED" else "FAILED"
        processed.completed_at = _now()
        return disposition, retries

    def process_claim(self, db: Session, claim_id: str, config_version: str = "intake-v1",
                      run_id: UUID | None = None) -> ProcessClaimResponse:
        # Reuse only runs produced under the same extraction and validator semantics.
        config_version = f"{config_version}|model={self.content_service.model}|{EXTRACTION_PROMPT_VERSION}|{EXTRACTION_VALIDATOR_VERSION}|{GEMINI_SCHEMA_ADAPTER_VERSION}"
        if db.query(IntakeClaim.id).filter_by(claim_id=claim_id).first() is None:
            raise DocumentProcessingError("Claim was not found.")
        resolved_items = None
        current_checksums = {}
        try:
            resolved_items = self._documents_for_claim(db, claim_id)
            for item in [resolved_items[0], *resolved_items[1]]:
                _, intake_doc, path, _ = item
                if (path.is_relative_to(intake_storage.LOCAL_DOCUMENT_ROOT.resolve()) and path.is_file()
                        and 0 < path.stat().st_size <= int(os.getenv("DOCUMENT_MAX_BYTES", str(10 * 1024 * 1024)))):
                    current_checksums[str(intake_doc.id)] = sha256(path.read_bytes()).hexdigest()
        except (DocumentProcessingError, OSError):
            resolved_items = None
        previous = db.query(ProcessingRun).filter_by(claim_id=claim_id, config_version=config_version).order_by(ProcessingRun.started_at.desc()).first()
        if previous is not None and previous.status != "RUNNING" and resolved_items is not None:
            docs = db.query(ProcessedDocument).filter_by(run_id=previous.id).order_by(ProcessedDocument.attempt_number).all()
            latest = {row.intake_document_id: row for row in docs}
            latest_by_public_id = {str(doc_id): row for doc_id, row in latest.items()}
            if set(current_checksums) == {str(doc_id) for doc_id in latest} and all(
                latest_by_public_id[doc_id].checksum_sha256 == checksum for doc_id, checksum in current_checksums.items()
            ):
                return ProcessClaimResponse(run_id=str(previous.id), claim_id=claim_id, status=previous.status,
                    policy_document_id=next((str(row.intake_document_id) for row in latest.values() if row.role == "policy_document"), None),
                    proof_document_ids=[str(doc_id) for doc_id, row in latest.items() if row.role != "policy_document" and row.status == "COMPLETED"],
                    failed_document_ids=[str(doc_id) for doc_id, row in latest.items() if row.status != "COMPLETED"], error=previous.error)
        run = ProcessingRun(id=run_id, claim_id=claim_id, config_version=config_version,
                            status="RUNNING", started_at=_now())
        db.add(run)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise DocumentProcessingError("A document-processing run is already active for this claim; retry after it finishes.") from exc
        except Exception as exc:
            db.rollback()
            raise DocumentProcessingError("Unable to persist the document-processing attempt.") from exc
        db.refresh(run)
        try:
            policy, proofs = resolved_items if resolved_items is not None else self._documents_for_claim(db, claim_id)
        except DocumentProcessingError as exc:
            run.status = "FAILED"
            run.error = str(exc)
            run.completed_at = _now()
            db.commit()
            return ProcessClaimResponse(run_id=str(run.id), claim_id=claim_id, status="FAILED", error=str(exc))
        completed, failed = [], []
        policy_id = str(policy[1].id)
        review_required = False
        for index, item in enumerate([policy, *proofs]):
            stored, intake_doc, _, role = item
            final_disposition = "FAILED"
            try:
                max_attempts = max(1, min(int(os.getenv("OCR_MAX_ATTEMPTS", "2")), 2))
                retry_pages = []
                for attempt_number in range(1, max_attempts + 1):
                    item_id = str(intake_doc.id)
                    item_role = "policy" if role == "policy_document" else "proof"
                    source_artifact = autopsy.artifact_id(
                        "source_document", {"sha256": intake_doc.checksum_sha256 or ""}, item_id=item_id,
                    )
                    with autopsy.stage(
                        "document_processing", item_id=item_id, item_role=item_role,
                        inputs=[source_artifact], attempt=attempt_number,
                    ) as stage:
                        stage.set_attribute("pipeline.stage.version", QUALITY_GATE_VERSION)
                        with stage.operation("file_validation"):
                            try:
                                digest, validated = self._validate_file(item)
                                stage.check(
                                    "document.file_valid", kind="schema", result="pass",
                                    action="continued", target=source_artifact,
                                )
                            except DocumentProcessingError as exc:
                                stage.check(
                                    "document.file_valid", kind="schema", result="fail",
                                    action="blocked", target=source_artifact,
                                    observed=exc.code or "FILE_VALIDATION_FAILED",
                                )
                                raise
                        self._check_ocr(validated)
                        attempt_config = {
                            "config_version": config_version,
                            "quality_gate_version": QUALITY_GATE_VERSION,
                            "quality_thresholds": self.quality_config.model_dump(),
                            "max_attempts": max_attempts,
                            "native_min_chars": int(os.getenv("OCR_NATIVE_MIN_CHARS", "24")),
                            "native_min_words": int(os.getenv("OCR_NATIVE_MIN_WORDS", "4")),
                            "render_dpi": int(os.getenv("OCR_RENDER_DPI", "200")),
                            "retry_render_dpi": int(os.getenv("OCR_RETRY_RENDER_DPI", "300")),
                            "page_timeout_seconds": float(os.getenv("OCR_PAGE_TIMEOUT_SECONDS", "45")),
                            "max_file_bytes": int(os.getenv("DOCUMENT_MAX_BYTES", str(10 * 1024 * 1024))),
                            "max_pages": int(os.getenv("DOCUMENT_MAX_PAGES", "100")),
                            "max_render_pixels": int(os.getenv("DOCUMENT_MAX_RENDER_PIXELS", "30000000")),
                            "tesseract_language": os.getenv("TESSERACT_LANGUAGE", "eng"),
                            "semantic_model": self.content_service.model,
                            "classification_prompt_version": "content-classification-v1",
                            "extraction_prompt_version": f"{EXTRACTION_PROMPT_VERSION}/per-document-type",
                            "semantic_schema_version": "document-facts-v1",
                            "retain_review_candidates": os.getenv("EXTRACTION_RETAIN_REVIEW_CANDIDATES", "false").strip().lower() in {"1", "true", "yes"},
                            "content_batch_chars": self.content_service.max_chars,
                            "content_batch_pages": self.content_service.max_pages,
                            "gemini_timeout_seconds": float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "45")),
                            "gemini_max_attempts": max(1, min(int(os.getenv("GEMINI_MAX_ATTEMPTS", "2")), 2)),
                            "gemini_max_concurrency": max(1, min(int(os.getenv("GEMINI_MAX_CONCURRENCY", "3")), 8)),
                        }
                        processed = ProcessedDocument(run_id=run.id, document_id=stored.id,
                            intake_document_id=intake_doc.id, claim_id=claim_id, role=role,
                            attempt_number=attempt_number, checksum_sha256=digest, status="RUNNING",
                            started_at=_now(), configuration=attempt_config)
                        db.add(processed)
                        db.commit()
                        with stage.operation("text_extraction"):
                            evidence = self.extractor.extract_evidence(validated,
                                force_ocr_pages=retry_pages if attempt_number > 1 else None,
                                render_dpi=int(attempt_config["retry_render_dpi"]) if attempt_number > 1 else None)
                            normalized = self.normalizer.normalize_evidence(evidence, document_id=stored.id)
                            faults.after_text_extraction(
                                {"document_id": str(intake_doc.id), "role": role},
                                normalized.pages,
                                normalized.processing_metadata["validation"],
                            )
                        validation = normalized.processing_metadata["validation"]
                        with stage.operation("quality_gate"):
                            retried_pages = bool(retry_pages)
                            final_disposition, retry_pages = self._persist_quality_attempt(
                                db, processed, normalized, retry_exhausted=attempt_number == max_attempts)
                            page_text = [
                                {"page": page.page_number, "method": page.extraction_method, "text": page.raw_text}
                                for page in normalized.pages
                            ]
                            page_text_id = stage.record_artifact(
                                kind="page_text", content=page_text, item_id=item_id,
                            )
                            low_ratio = validation.get("low_confidence_word_proportion")
                            low_ratio_label = f"{low_ratio:.2f}" if isinstance(low_ratio, (int, float)) else "na"
                            min_chars_ok = all(
                                row.get("character_count", 0) >= self.quality_config.min_character_count
                                or row.get("status") == "BLANK"
                                for row in validation.get("page_validations", [])
                            )
                            quality_result = "pass" if final_disposition == "ACCEPTED" else (
                                "fail" if processed.quality_status == "FAIL" else "warn"
                            )
                            stage.check(
                                "ocr.quality", kind="threshold", result=quality_result,
                                action="continued" if final_disposition == "ACCEPTED" else "review",
                                target=page_text_id,
                                observed=f"low_conf_ratio={low_ratio_label};min_chars_ok={str(min_chars_ok).lower()}",
                                expected=f"low_conf_ratio<={self.quality_config.max_low_confidence_ratio:g};min_chars_ok=true",
                            )
                            retry_exhausted = attempt_number == max_attempts and any(
                                "retry limit was reached" in reason.lower()
                                for reason in processed.validation_reasons
                            )
                            retry_exhausted = retry_exhausted or (
                                attempt_number == max_attempts and retried_pages
                            )
                            if retry_exhausted:
                                stage.check(
                                    "ocr.retry_exhausted", kind="threshold", result="warn", action="review",
                                    target=page_text_id, observed=f"attempt={attempt_number}",
                                    expected=f"attempt<={max_attempts}",
                                )
                            if final_disposition != "ACCEPTED":
                                stage.set_status("partial")
                            db.commit()
                    if final_disposition == "RETRY_REQUIRED" and attempt_number < max_attempts:
                        continue
                    break
                if final_disposition != "ACCEPTED" and processed.quality_status == "FAIL":
                    final_disposition = "UNREADABLE"
                    processed.disposition = "UNREADABLE"
                    processed.status = "UNREADABLE"
                    db.commit()
                if final_disposition == "ACCEPTED":
                    semantic_status = self.content_service.process_and_persist(
                        db, processed, normalized, declared_type=role, checksum=digest)
                    if semantic_status != "accepted":
                        status_map = {
                            "content_mismatch": ("CONTENT_MISMATCH", "CONTENT_MISMATCH"),
                            "review_required": ("REVIEW_REQUIRED", "HUMAN_REVIEW_REQUIRED"),
                            "unreadable": ("UNREADABLE", "UNREADABLE"),
                            "classification_failed": ("CLASSIFICATION_FAILED", "CLASSIFICATION_FAILED"),
                        }
                        processed.status, final_disposition = status_map.get(
                            semantic_status, ("REVIEW_REQUIRED", "HUMAN_REVIEW_REQUIRED"))
                        processed.disposition = final_disposition
                        processed.error = ("Document classification failed technically." if semantic_status == "classification_failed"
                            else "Document content validation or structured extraction requires correction or review.")
                        processed.completed_at = _now()
                        db.commit()
                if final_disposition == "ACCEPTED":
                    if index:
                        completed.append(str(intake_doc.id))
                else:
                    failed.append(str(intake_doc.id))
                    review_required = True
                    if index == 0:
                        run.status = "REVIEW_REQUIRED"
                        run.error = "Policy processing gates were not accepted; proof processing was blocked."
                        self._record_blocked_proofs(db, run, claim_id, proofs, failed, config_version)
                        break
            except Exception as exc:
                db.rollback()
                failed.append(policy_id if index == 0 else str(intake_doc.id))
                processed = db.query(ProcessedDocument).filter_by(
                    run_id=run.id, document_id=stored.id).order_by(ProcessedDocument.attempt_number.desc()).first()
                if processed is None:
                    processed = ProcessedDocument(run_id=run.id, document_id=stored.id,
                        intake_document_id=intake_doc.id, claim_id=claim_id, role=role,
                        attempt_number=1, checksum_sha256=intake_doc.checksum_sha256, status="TECHNICAL_FAILURE",
                        disposition="TECHNICAL_FAILURE", started_at=_now(), completed_at=_now(),
                        error=f"Processing failed ({type(exc).__name__}).",
                        configuration={"config_version": config_version, "quality_gate_version": QUALITY_GATE_VERSION})
                    db.add(processed)
                else:
                    processed.status = "TECHNICAL_FAILURE"
                    processed.disposition = "TECHNICAL_FAILURE"
                    processed.completed_at = _now()
                    processed.error = f"Processing failed ({type(exc).__name__})."
                db.commit()
                if index == 0:
                    run.status = "FAILED"
                    detail = str(exc) if isinstance(exc, DocumentProcessingError) else f"Processing failed ({type(exc).__name__})."
                    run.error = f"Policy processing failed; proof processing was blocked: {detail}"
                    self._record_blocked_proofs(db, run, claim_id, proofs, failed, config_version)
                    break
        else:
            run.status = "REVIEW_REQUIRED" if review_required else "PARTIAL" if failed else "COMPLETED"
        run.completed_at = _now()
        db.commit()
        return ProcessClaimResponse(run_id=str(run.id), claim_id=claim_id, status=run.status,
            policy_document_id=policy_id, proof_document_ids=completed, failed_document_ids=failed, error=run.error)


claim_document_processing_service = ClaimDocumentProcessingService()
