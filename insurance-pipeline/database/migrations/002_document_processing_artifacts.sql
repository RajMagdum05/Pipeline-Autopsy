CREATE TABLE IF NOT EXISTS document_processing_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    config_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    error TEXT
);
CREATE INDEX IF NOT EXISTS ix_document_processing_runs_claim_id ON document_processing_runs (claim_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_document_processing_claim
    ON document_processing_runs (claim_id) WHERE status = 'RUNNING';

CREATE TABLE IF NOT EXISTS processed_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES document_processing_runs(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    intake_document_id UUID NOT NULL REFERENCES claim_documents(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    checksum_sha256 VARCHAR(64),
    status TEXT NOT NULL DEFAULT 'PENDING',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    quality_status TEXT,
    engine TEXT,
    engine_version TEXT,
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    disposition TEXT NOT NULL DEFAULT 'RUNNING',
    confidence_score DOUBLE PRECISION,
    confidence_source TEXT,
    confidence_scale TEXT,
    confidence_aggregation_method TEXT,
    confidence_word_count INTEGER NOT NULL DEFAULT 0,
    confidence_missing_word_count INTEGER NOT NULL DEFAULT 0,
    confidence_coverage DOUBLE PRECISION,
    low_confidence_word_count INTEGER NOT NULL DEFAULT 0,
    low_confidence_word_proportion DOUBLE PRECISION,
    quality_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT uq_processed_run_document_attempt UNIQUE (run_id, document_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS ix_processed_documents_run_id ON processed_documents (run_id);
CREATE INDEX IF NOT EXISTS ix_processed_documents_document_id ON processed_documents (document_id);
CREATE INDEX IF NOT EXISTS ix_processed_documents_intake_document_id ON processed_documents (intake_document_id);
CREATE INDEX IF NOT EXISTS ix_processed_documents_claim_id ON processed_documents (claim_id);

CREATE TABLE IF NOT EXISTS processed_document_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processed_document_id UUID NOT NULL REFERENCES processed_documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    engine TEXT NOT NULL,
    engine_version TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    disposition TEXT NOT NULL,
    confidence_score DOUBLE PRECISION,
    confidence_source TEXT,
    confidence_scale TEXT,
    confidence_aggregation_method TEXT,
    confidence_word_count INTEGER NOT NULL DEFAULT 0,
    confidence_missing_word_count INTEGER NOT NULL DEFAULT 0,
    confidence_coverage DOUBLE PRECISION,
    low_confidence_word_count INTEGER NOT NULL DEFAULT 0,
    low_confidence_word_proportion DOUBLE PRECISION,
    quality_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_text TEXT NOT NULL DEFAULT '',
    layout JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    CONSTRAINT uq_processed_page_number UNIQUE (processed_document_id, page_number)
);
CREATE INDEX IF NOT EXISTS ix_processed_document_pages_processed_document_id ON processed_document_pages (processed_document_id);
