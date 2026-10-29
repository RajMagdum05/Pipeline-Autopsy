import json
import os
import uuid
from typing import Any, Optional, Union
from google import genai
from google.genai import types

from app.schemas import ClaimReasoningResult, ExtractedClaimInformation
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.telemetry.attributes import (
    PIPELINE_NAME,
    PIPELINE_NAME_VAL,
    PIPELINE_VERSION,
    PIPELINE_VERSION_VAL,
    EXECUTION_ID,
    EXECUTION_ENTITY_ID,
    STAGE_NAME,
    STAGE_VERSION,
    STAGE_STATUS,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    RETRY_COUNT,
    RETRY_REASON,
    RETRY_ATTEMPT_NUMBER,
)

tracer = trace.get_tracer("enterprise_pipeline.reasoning")


class ReasoningServiceError(Exception):
    """Custom exception raised when policy reasoning fails."""
    pass


def evaluate_claim_against_policy(
    claim_info: ExtractedClaimInformation | dict[str, Any],
    policy_chunks: list[dict[str, Any]] | list[str],
    claim_id: Optional[Union[int, str]] = None,
    execution_id: Optional[str] = None,
) -> ClaimReasoningResult:
    """
    Evaluates structured claim information against retrieved policy context using LLM reasoning.
    
    Returns structured ClaimReasoningResult containing:
      - eligible: bool | None (True if covered, False if excluded/over limit, None if uncertain)
      - reasoning: str (Step-by-step justification based ONLY on evidence)
      - supporting_policy_text: str | None (Relevant policy clause text)
      - confidence: float (0.0 to 1.0 confidence score)
    """
    # Normalize claim info to dictionary/JSON string
    if isinstance(claim_info, ExtractedClaimInformation):
        claim_dict = claim_info.model_dump()
    elif isinstance(claim_info, dict):
        claim_dict = claim_info
    else:
        raise ReasoningServiceError("Invalid claim_info type. Expected ExtractedClaimInformation or dict.")

    # Resolve context (claim_id, execution_id)
    curr_claim_id = claim_id or claim_dict.get("claim_id")
    curr_exec_id = execution_id
    if not curr_claim_id or not curr_exec_id:
        curr_span = trace.get_current_span()
        if curr_span and hasattr(curr_span, "attributes") and curr_span.attributes:
            curr_claim_id = curr_claim_id or curr_span.attributes.get("claim_id") or curr_span.attributes.get("execution.entity_id")
            curr_exec_id = curr_exec_id or curr_span.attributes.get("execution.id")
    curr_claim_id = curr_claim_id or 1
    curr_exec_id = curr_exec_id or f"EXEC-{uuid.uuid4().hex[:12].upper()}"

    in_artifacts = [f"art_extracted_claim_{curr_claim_id}", f"art_policy_context_{curr_claim_id}"]
    out_artifacts = [f"art_reasoning_claim_{curr_claim_id}"]

    with tracer.start_as_current_span("reasoning_service") as span:
        span.set_attribute("claim_id", curr_claim_id)
        span.set_attribute(EXECUTION_ID, curr_exec_id)
        span.set_attribute(EXECUTION_ENTITY_ID, str(curr_claim_id))
        span.set_attribute(PIPELINE_NAME, PIPELINE_NAME_VAL)
        span.set_attribute(PIPELINE_VERSION, PIPELINE_VERSION_VAL)
        span.set_attribute(STAGE_NAME, "reasoning_service")
        span.set_attribute(STAGE_VERSION, "1.0.0")
        span.set_attribute(INPUT_ARTIFACT_IDS, in_artifacts)
        span.set_attribute(OUTPUT_ARTIFACT_IDS, out_artifacts)

        # Build non-sensitive extracted values used (exclude PII like customer_name, patient_name)
        extracted_values_used = {}
        for k in ("diagnosis", "treatment", "date", "amount", "hospital"):
            if k in claim_dict and claim_dict[k] is not None:
                extracted_values_used[k] = str(claim_dict[k])
        span.set_attribute("reasoning.extracted_values_used", json.dumps(extracted_values_used))

        # Extract retrieved chunk IDs used
        formatted_chunks = []
        retrieved_chunk_ids = []
        if isinstance(policy_chunks, list):
            for idx, item in enumerate(policy_chunks, 1):
                if isinstance(item, dict):
                    text = item.get("chunk_text") or item.get("text") or str(item)
                    name = item.get("policy_name", f"Chunk {idx}")
                    chunk_id = item.get("chunk_id") or item.get("id") or name
                    retrieved_chunk_ids.append(str(chunk_id))
                    formatted_chunks.append(f"[{name}]\n{text}")
                else:
                    retrieved_chunk_ids.append(f"chunk_{idx}")
                    formatted_chunks.append(f"[Chunk {idx}]\n{str(item)}")

        span.set_attribute("reasoning.retrieved_chunk_ids_used", retrieved_chunk_ids)
        span.set_attribute("model.name", "gemini-3.6-flash")
        span.set_attribute("model.version", "1.0.0")
        span.set_attribute("prompt.version", "v1.0-policy-reasoning")
        span.set_attribute(RETRY_COUNT, 0)

        policy_text_block = "\n\n".join(formatted_chunks) if formatted_chunks else "No policy context provided."

        # Verify API key
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            err = ReasoningServiceError("Missing GEMINI_API_KEY environment variable.")
            span.record_exception(err)
            span.set_attribute(STAGE_STATUS, "failed")
            span.set_attribute("error.type", type(err).__name__)
            span.set_attribute("error.message", str(err))
            span.set_status(Status(StatusCode.ERROR, str(err)))
            raise err

        try:
            client = genai.Client(api_key=api_key)

            prompt = f"""You are an expert insurance claim policy evaluation reasoning engine.
Evaluate whether the following insurance claim satisfies the provided policy coverage terms.

Strict Reasoning Guidelines:
1. Base your evaluation ONLY on the provided Claim Details and Policy Context.
2. DO NOT invent, assume, or assume any unstated policy rules or claim facts.
3. Determine 'eligible':
   - true: if the claim treatment/diagnosis is explicitly covered AND the claim amount is within the policy coverage limit.
   - false: if the treatment is explicitly excluded OR the claim amount exceeds the policy limit.
   - null/None: if the policy context is missing or insufficient to make a definitive determination.
4. Provide step-by-step logical 'reasoning'.
5. Quote the relevant 'supporting_policy_text'.
6. Provide a 'confidence' score between 0.0 and 1.0.

Claim Details:
{json.dumps(claim_dict, indent=2, default=str)}

Retrieved Policy Context:
---
{policy_text_block}
---
"""

            # Call Gemini API with structured JSON output enforcing ClaimReasoningResult schema
            max_retries = 3
            response = None
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model="gemini-3.6-flash",
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ClaimReasoningResult,
                        ),
                    )
                    break
                except Exception as api_err:
                    err_str = str(api_err)
                    clean_reason = err_str.replace(api_key, "[REDACTED_API_KEY]")
                    span.set_attribute(RETRY_COUNT, attempt + 1)
                    span.set_attribute(RETRY_ATTEMPT_NUMBER, attempt + 1)
                    span.set_attribute(RETRY_REASON, clean_reason)
                    if "503" in err_str and attempt < max_retries - 1:
                        import time
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise api_err

            if not response or not response.text:
                raise ReasoningServiceError("LLM reasoning API returned an empty response.")

            result = ClaimReasoningResult.model_validate_json(response.text)
            res_str = "APPROVED" if result.eligible is True else ("DENIED" if result.eligible is False else "UNCERTAIN")
            span.set_attribute("reasoning.result", res_str)
            span.set_attribute(STAGE_STATUS, "completed")
            span.set_status(Status(StatusCode.OK))
            return result

        except ReasoningServiceError as rse:
            span.record_exception(rse)
            span.set_attribute(STAGE_STATUS, "failed")
            span.set_attribute("error.type", type(rse).__name__)
            span.set_attribute("error.message", str(rse))
            span.set_status(Status(StatusCode.ERROR, str(rse)))
            raise
        except Exception as e:
            wrapped_exc = ReasoningServiceError(f"Policy reasoning evaluation failed: {str(e)}")
            span.record_exception(wrapped_exc)
            span.set_attribute(STAGE_STATUS, "failed")
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise wrapped_exc from e
