"""
Standard OpenTelemetry trace attribute keys as defined by /shared-docs/TRACE_CONTRACT.md.
"""

# Required Contract Attributes (Strictly Required for all spans)
PIPELINE_NAME = "pipeline.name"
PIPELINE_VERSION = "pipeline.version"
EXECUTION_ID = "execution.id"
EXECUTION_ENTITY_ID = "execution.entity_id"
STAGE_NAME = "stage.name"
STAGE_STATUS = "stage.status"
INPUT_ARTIFACT_IDS = "input.artifact_ids"
OUTPUT_ARTIFACT_IDS = "output.artifact_ids"

# Recommended Contract Attributes
STAGE_VERSION = "stage.version"
MODEL_NAME = "model.name"
MODEL_VERSION = "model.version"
PROMPT_VERSION = "prompt.version"
RETRIEVAL_QUERY = "retrieval.query"
RETRIEVAL_CHUNK_IDS = "retrieval.chunk_ids"
ERROR_TYPE = "error.type"
ERROR_MESSAGE = "error.message"
VALIDATION_RULE_ID = "validation.rule_id"
VALIDATION_RESULT = "validation.result"
VALIDATION_STATUS = "validation.status"
DECISION_RESULT = "decision.result"
DOCUMENTS_TOTAL_COUNT = "documents.total_count"
CLAIM_AMOUNT = "claim.amount"

# Retry and Error Attributes
RETRY_COUNT = "retry.count"
RETRY_REASON = "retry.reason"
RETRY_ATTEMPT_NUMBER = "retry.attempt_number"

# Default Service Identity
DEFAULT_PIPELINE_NAME = "insurance-pipeline"
DEFAULT_PIPELINE_VERSION = "1.0.0"
PIPELINE_NAME_VAL = DEFAULT_PIPELINE_NAME
PIPELINE_VERSION_VAL = DEFAULT_PIPELINE_VERSION

