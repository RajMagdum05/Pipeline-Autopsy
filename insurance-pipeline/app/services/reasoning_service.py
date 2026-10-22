import json
import os
from typing import Any
from google import genai
from google.genai import types

from app.schemas import ClaimReasoningResult, ExtractedClaimInformation


class ReasoningServiceError(Exception):
    """Custom exception raised when policy reasoning fails."""
    pass


def evaluate_claim_against_policy(
    claim_info: ExtractedClaimInformation | dict[str, Any],
    policy_chunks: list[dict[str, Any]] | list[str],
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

    # Format policy chunks into readable text
    formatted_chunks = []
    if isinstance(policy_chunks, list):
        for idx, item in enumerate(policy_chunks, 1):
            if isinstance(item, dict):
                text = item.get("chunk_text") or item.get("text") or str(item)
                name = item.get("policy_name", f"Chunk {idx}")
                formatted_chunks.append(f"[{name}]\n{text}")
            else:
                formatted_chunks.append(f"[Chunk {idx}]\n{str(item)}")
    
    policy_text_block = "\n\n".join(formatted_chunks) if formatted_chunks else "No policy context provided."

    # Verify API key
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ReasoningServiceError("Missing GEMINI_API_KEY environment variable.")

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
                if "503" in str(api_err) and attempt < max_retries - 1:
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue
                raise api_err

        if not response.text:
            raise ReasoningServiceError("LLM reasoning API returned an empty response.")

        return ClaimReasoningResult.model_validate_json(response.text)


    except ReasoningServiceError:
        raise
    except Exception as e:
        raise ReasoningServiceError(f"Policy reasoning evaluation failed: {str(e)}") from e
