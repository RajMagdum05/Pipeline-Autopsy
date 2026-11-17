CREATE TABLE IF NOT EXISTS feedback (
    id VARCHAR(64) PRIMARY KEY,
    finding_id VARCHAR(64) NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    verdict VARCHAR(16) NOT NULL,
    comment TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_feedback_finding_id ON feedback (finding_id);
