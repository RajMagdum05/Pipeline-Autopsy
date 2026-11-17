-- Stage 1 intake schema. The current integer-ID claims table is renamed to
-- legacy_claims by app.database.init_db before these statements are applied.

CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_id INTEGER UNIQUE,
    claim_id TEXT NOT NULL UNIQUE,
    policyholder_name TEXT NOT NULL,
    age INTEGER NOT NULL CHECK (age >= 0 AND age <= 120),
    policy_number TEXT NOT NULL,
    incident_date DATE NOT NULL,
    description TEXT NOT NULL,
    claimed_amount NUMERIC(12,2) NOT NULL CHECK (claimed_amount > 0),
    claim_status TEXT NOT NULL DEFAULT 'submitted',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claim_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    document_slot INTEGER NOT NULL CHECK (document_slot BETWEEN 0 AND 3),
    document_type TEXT CHECK (
        document_type IS NULL OR document_type IN (
            'policy_document', 'hospital_bill', 'fir_accident_report',
            'medical_report', 'discharge_summary', 'repair_estimate',
            'other_supporting_document'
        )
    ),
    original_file_name TEXT,
    stored_file_name TEXT,
    storage_path TEXT,
    mime_type TEXT,
    file_size_bytes BIGINT,
    checksum_sha256 TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_claim_documents_claim_slot UNIQUE (claim_id, document_slot)
);

CREATE INDEX IF NOT EXISTS ix_claim_documents_claim_id ON claim_documents (claim_id);
