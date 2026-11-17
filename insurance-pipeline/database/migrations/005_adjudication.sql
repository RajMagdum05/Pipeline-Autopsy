CREATE TABLE IF NOT EXISTS adjudication_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL UNIQUE REFERENCES document_processing_runs(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    rules_version TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED', 'MANUAL_REVIEW')),
    payable_amount NUMERIC(12,2),
    rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    inputs_checksum VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_adjudication_results_claim_id ON adjudication_results(claim_id);
