ALTER TABLE claims ADD COLUMN IF NOT EXISTS access_token_hash VARCHAR(64);
ALTER TABLE claim_documents ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS claim_document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_document_id UUID NOT NULL REFERENCES claim_documents(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    original_file_name TEXT,
    stored_file_name TEXT,
    storage_path TEXT,
    mime_type TEXT,
    file_size_bytes BIGINT,
    checksum_sha256 VARCHAR(64),
    version_number INTEGER NOT NULL,
    uploaded_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ocr_result JSONB,
    ocr_record JSONB,
    CONSTRAINT uq_claim_document_version UNIQUE (claim_document_id, version_number)
);
CREATE INDEX IF NOT EXISTS ix_claim_document_versions_claim_document_id ON claim_document_versions(claim_document_id);
CREATE INDEX IF NOT EXISTS ix_claim_document_versions_claim_id ON claim_document_versions(claim_id);
