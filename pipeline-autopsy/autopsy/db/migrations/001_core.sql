CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(32) PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO projects (id, name, created_at)
VALUES ('default', 'Default', CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS pipelines (
    project_id VARCHAR(64) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(64) NOT NULL,
    version VARCHAR(64) NOT NULL,
    manifest JSON_TYPE NOT NULL DEFAULT '{}',
    evidence_level VARCHAR(2) NOT NULL DEFAULT 'E1',
    evidence_kinds_allowed JSON_TYPE NOT NULL DEFAULT '[]',
    retention_days INTEGER NOT NULL DEFAULT 14,
    registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, name, version)
);

CREATE TABLE IF NOT EXISTS executions (
    id VARCHAR(64) PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pipeline VARCHAR(64) NOT NULL,
    version VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64),
    trace_ids JSON_TYPE NOT NULL DEFAULT '[]',
    status VARCHAR(24) NOT NULL DEFAULT 'receiving',
    verdict VARCHAR(64),
    trace_grade VARCHAR(1),
    run_outcome VARCHAR(16),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    diagnosed_at TIMESTAMP,
    previous_execution_id VARCHAR(64) REFERENCES executions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS spans (
    trace_id VARCHAR(32) NOT NULL,
    span_id VARCHAR(16) NOT NULL,
    execution_id VARCHAR(64) NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    parent_span_id VARCHAR(16),
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(16) NOT NULL DEFAULT 'INTERNAL',
    role VARCHAR(16) NOT NULL DEFAULT 'other',
    stage_name VARCHAR(128),
    item_id VARCHAR(128),
    attempt INTEGER,
    status VARCHAR(8) NOT NULL DEFAULT 'UNSET',
    status_message TEXT,
    error_type VARCHAR(255),
    error_class VARCHAR(32),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    attrs JSON_TYPE NOT NULL DEFAULT '{}',
    events JSON_TYPE NOT NULL DEFAULT '[]',
    links JSON_TYPE NOT NULL DEFAULT '[]',
    resource JSON_TYPE NOT NULL DEFAULT '{}',
    dropped_attributes INTEGER NOT NULL DEFAULT 0,
    dropped_events INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (trace_id, span_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id VARCHAR(64) PRIMARY KEY,
    execution_id VARCHAR(64) NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    stage VARCHAR(128),
    item_id VARCHAR(128),
    kind VARCHAR(64) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    blob_path TEXT NOT NULL,
    redacted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS diagnosis_jobs (
    execution_id VARCHAR(64) PRIMARY KEY REFERENCES executions(id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    reason VARCHAR(16),
    run_after TIMESTAMP,
    attempt INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observations (
    execution_id VARCHAR(64) NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    id VARCHAR(64) NOT NULL,
    family VARCHAR(32) NOT NULL,
    code VARCHAR(128) NOT NULL,
    result VARCHAR(16) NOT NULL,
    stage VARCHAR(128),
    span_id VARCHAR(16),
    artifact_id VARCHAR(64),
    field VARCHAR(128),
    reported_by VARCHAR(128),
    error_class VARCHAR(32),
    source_artifact_id VARCHAR(64),
    detail TEXT NOT NULL,
    PRIMARY KEY (execution_id, id)
);

CREATE TABLE IF NOT EXISTS findings (
    id VARCHAR(64) PRIMARY KEY,
    execution_id VARCHAR(64) NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    stage VARCHAR(128),
    item_id VARCHAR(128),
    role VARCHAR(16) NOT NULL,
    classification VARCHAR(64),
    confidence VARCHAR(16),
    severity VARCHAR(16),
    link VARCHAR(16),
    caused_by JSON_TYPE NOT NULL DEFAULT '[]',
    evidence JSON_TYPE NOT NULL DEFAULT '[]',
    note TEXT,
    signature VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS explanations (
    execution_id VARCHAR(64) PRIMARY KEY REFERENCES executions(id) ON DELETE CASCADE,
    source VARCHAR(16) NOT NULL,
    summary TEXT NOT NULL,
    narrative JSON_TYPE NOT NULL DEFAULT '[]',
    remediation JSON_TYPE NOT NULL DEFAULT '[]',
    guardrail_log JSON_TYPE NOT NULL DEFAULT '[]',
    model VARCHAR(128),
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_ms FLOAT
);

CREATE INDEX IF NOT EXISTS idx_executions_pipeline_started_at ON executions (pipeline, started_at);
CREATE INDEX IF NOT EXISTS ix_executions_project_id ON executions (project_id);
CREATE INDEX IF NOT EXISTS ix_executions_entity_id ON executions (entity_id);
CREATE INDEX IF NOT EXISTS ix_executions_status ON executions (status);
CREATE INDEX IF NOT EXISTS ix_executions_started_at ON executions (started_at);
CREATE INDEX IF NOT EXISTS ix_spans_execution_id ON spans (execution_id);
CREATE INDEX IF NOT EXISTS ix_spans_parent_span_id ON spans (parent_span_id);
CREATE INDEX IF NOT EXISTS ix_spans_role ON spans (role);
CREATE INDEX IF NOT EXISTS ix_spans_stage_name ON spans (stage_name);
CREATE INDEX IF NOT EXISTS ix_spans_item_id ON spans (item_id);
CREATE INDEX IF NOT EXISTS ix_spans_status ON spans (status);
CREATE INDEX IF NOT EXISTS ix_spans_error_type ON spans (error_type);
CREATE INDEX IF NOT EXISTS ix_spans_error_class ON spans (error_class);
CREATE INDEX IF NOT EXISTS ix_spans_start_time ON spans (start_time);
CREATE INDEX IF NOT EXISTS idx_spans_role_stage ON spans (role, stage_name);
CREATE INDEX IF NOT EXISTS ix_artifacts_execution_id ON artifacts (execution_id);
CREATE INDEX IF NOT EXISTS ix_diagnosis_jobs_status ON diagnosis_jobs (status);
CREATE INDEX IF NOT EXISTS ix_diagnosis_jobs_run_after ON diagnosis_jobs (run_after);
CREATE INDEX IF NOT EXISTS idx_diagnosis_jobs_status_run_after ON diagnosis_jobs (status, run_after);
CREATE INDEX IF NOT EXISTS ix_findings_execution_id ON findings (execution_id);
CREATE INDEX IF NOT EXISTS ix_findings_signature ON findings (signature);
