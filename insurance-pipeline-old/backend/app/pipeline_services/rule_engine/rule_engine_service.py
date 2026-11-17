import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Optional

from app.schemas import (
    ValidatedExtractionResult,
    ClaimExtractionResult,
    RuleResult,
    RuleEngineDecision,
)

from opentelemetry import trace
from app.telemetry.span_helpers import stage_span
from app.telemetry.attributes import OUTPUT_ARTIFACT_IDS

tracer = trace.get_tracer("enterprise_pipeline.rule_engine")

logger = logging.getLogger("enterprise_pipeline.rule_engine")

# Fixed policy threshold constants
MAX_POLICY_COVERAGE_LIMIT = Decimal("100000.00")


class RuleEngineError(Exception):
    """Base exception class for Rule Engine failures."""
    pass


class RuleEngineInputError(RuleEngineError):
    """Raised when unvalidated or malformed extraction inputs are passed to the Rule Engine."""
    pass


def evaluate_claim_rules(
    extraction_input: Union[ValidatedExtractionResult, ClaimExtractionResult, Dict[str, Any]],
    db_session: Any = None,
) -> RuleEngineDecision:
    """
    Evaluates deterministic business rules against a validated Information Extraction result.

    Rules are evaluated independently; evaluation does NOT stop at the first failed rule.
    Missing fields are explicitly handled as MISSING_DATA without implicit type coercion.

    Args:
        extraction_input: Validated extraction result object or dict.
        db_session: Optional SQLAlchemy database session for result persistence.

    Returns:
        RuleEngineDecision: Complete decision summary and independent rule evaluation results.

    Raises:
        RuleEngineInputError: If extraction_input is unvalidated or failed.
    """
    if isinstance(extraction_input, dict):
        stage_claim_id = extraction_input.get("claim_id")
        stage_execution_id = extraction_input.get("execution_id")
    else:
        stage_claim_id = getattr(extraction_input, "claim_id", None)
        stage_execution_id = getattr(extraction_input, "execution_id", None)

    claim_key = str(stage_claim_id) if stage_claim_id is not None else "unknown"
    execution_key = str(stage_execution_id) if stage_execution_id else "exec_unknown"
    input_artifact_ids = (
        [f"art_entities_claim_{stage_claim_id}"] if stage_claim_id is not None else []
    )

    with stage_span(
        tracer=tracer,
        stage_name="rule_engine",
        execution_id=execution_key,
        entity_id=claim_key,
        input_artifact_ids=input_artifact_ids,
        safe_error_message="Rule engine evaluation failed.",
    ) as span:
        try:
            # 1. Input Gatekeeping Check
            if isinstance(extraction_input, ValidatedExtractionResult):
                if not extraction_input.ready_for_rule_engine or extraction_input.extraction_status != "VALIDATED":
                    err = RuleEngineInputError(
                        f"Cannot evaluate extraction input with status '{extraction_input.extraction_status}'. "
                        "Rule Engine requires extraction_status == 'VALIDATED'."
                    )
                    raise err
                data = extraction_input.model_dump()
                claim_id = extraction_input.claim_id
                execution_id = extraction_input.execution_id
            elif isinstance(extraction_input, ClaimExtractionResult):
                data = extraction_input.model_dump()
                claim_id = extraction_input.claim_id
                execution_id = data.get("execution_id") or "exec_legacy_001"
            elif isinstance(extraction_input, dict):
                if extraction_input.get("extraction_status") == "FAILED" or extraction_input.get("ready_for_rule_engine") is False:
                    err = RuleEngineInputError("Cannot evaluate failed extraction input payload.")
                    raise err
                data = extraction_input
                claim_id = data.get("claim_id", 1)
                execution_id = data.get("execution_id", "exec_dict_001")
            else:
                err = RuleEngineInputError(f"Unsupported extraction input type: {type(extraction_input)}")
                raise err

            span.set_attribute("claim_id", claim_id)
            span.set_attribute("execution_id", str(execution_id))

            # Extract field values
            patient_name = data.get("patient_name")
            hospital = data.get("hospital")
            diagnosis = data.get("diagnosis")
            treatment = data.get("treatment")
            date_val = data.get("date")
            amount_raw = data.get("amount")

            evaluated_rules: List[RuleResult] = []

            # -------------------------------------------------------------------------
            # RULE 1: Patient Name Presence Check (RULE_001_PATIENT_NAME_PRESENT)
            # -------------------------------------------------------------------------
            rule_1_id = "RULE_001_PATIENT_NAME_PRESENT"
            rule_1_name = "Patient Name Presence Check"
            rule_1_expected = "patient_name must be present and non-empty"
            rule_1_input = {"patient_name": patient_name}

            if not patient_name or not str(patient_name).strip():
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_1_id,
                        rule_name=rule_1_name,
                        input_values=rule_1_input,
                        expected_condition=rule_1_expected,
                        actual_value=patient_name,
                        result="MISSING_DATA",
                        reason="Patient name is missing from extracted claim information.",
                    )
                )
            else:
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_1_id,
                        rule_name=rule_1_name,
                        input_values=rule_1_input,
                        expected_condition=rule_1_expected,
                        actual_value=str(patient_name).strip(),
                        result="PASS",
                        reason=f"Valid patient name '{patient_name}' present.",
                    )
                )

            # -------------------------------------------------------------------------
            # RULE 2: Maximum Policy Coverage Limit Check (RULE_002_MAX_CLAIM_AMOUNT_LIMIT)
            # -------------------------------------------------------------------------
            rule_2_id = "RULE_002_MAX_CLAIM_AMOUNT_LIMIT"
            rule_2_name = "Maximum Policy Coverage Limit Check"
            rule_2_expected = f"amount must be <= ${MAX_POLICY_COVERAGE_LIMIT:,.2f}"
            rule_2_input = {"amount": str(amount_raw) if amount_raw is not None else None}

            if amount_raw is None:
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_2_id,
                        rule_name=rule_2_name,
                        input_values=rule_2_input,
                        expected_condition=rule_2_expected,
                        actual_value=None,
                        result="MISSING_DATA",
                        reason="Claim amount is missing from extracted claim information.",
                    )
                )
            else:
                try:
                    amount_dec = Decimal(str(amount_raw).replace("$", "").replace(",", "").strip())
                    if amount_dec <= MAX_POLICY_COVERAGE_LIMIT:
                        evaluated_rules.append(
                            RuleResult(
                                rule_id=rule_2_id,
                                rule_name=rule_2_name,
                                input_values=rule_2_input,
                                expected_condition=rule_2_expected,
                                actual_value=float(amount_dec),
                                result="PASS",
                                reason=f"Claim amount ${amount_dec:,.2f} is within maximum policy coverage limit of ${MAX_POLICY_COVERAGE_LIMIT:,.2f}.",
                            )
                        )
                    else:
                        evaluated_rules.append(
                            RuleResult(
                                rule_id=rule_2_id,
                                rule_name=rule_2_name,
                                input_values=rule_2_input,
                                expected_condition=rule_2_expected,
                                actual_value=float(amount_dec),
                                result="FAIL",
                                reason=f"Claim amount ${amount_dec:,.2f} exceeds maximum policy coverage limit of ${MAX_POLICY_COVERAGE_LIMIT:,.2f}.",
                            )
                        )
                except Exception as amt_err:
                    evaluated_rules.append(
                        RuleResult(
                            rule_id=rule_2_id,
                            rule_name=rule_2_name,
                            input_values=rule_2_input,
                            expected_condition=rule_2_expected,
                            actual_value=str(amount_raw),
                            result="FAIL",
                            reason=f"Claim amount '{amount_raw}' is non-numeric and cannot be evaluated against policy limit.",
                        )
                    )

            # -------------------------------------------------------------------------
            # RULE 3: Medical Provider / Treatment Presence Check (RULE_003_TREATMENT_PRESENT)
            # -------------------------------------------------------------------------
            rule_3_id = "RULE_003_TREATMENT_PRESENT"
            rule_3_name = "Medical Provider / Treatment Presence Check"
            rule_3_expected = "hospital provider or treatment details must be specified"
            rule_3_input = {"hospital": hospital, "treatment": treatment}

            has_hospital = bool(hospital and str(hospital).strip())
            has_treatment = bool(treatment and str(treatment).strip())

            if not has_hospital and not has_treatment:
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_3_id,
                        rule_name=rule_3_name,
                        input_values=rule_3_input,
                        expected_condition=rule_3_expected,
                        actual_value=None,
                        result="MISSING_DATA",
                        reason="Neither hospital provider nor treatment details are specified in claim.",
                    )
                )
            else:
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_3_id,
                        rule_name=rule_3_name,
                        input_values=rule_3_input,
                        expected_condition=rule_3_expected,
                        actual_value=f"Hospital: '{hospital or 'N/A'}', Treatment: '{treatment or 'N/A'}'",
                        result="PASS",
                        reason=f"Medical provider ('{hospital or 'N/A'}') / treatment ('{treatment or 'N/A'}') verified.",
                    )
                )

            # -------------------------------------------------------------------------
            # RULE 4: Medical Diagnosis Presence Check (RULE_004_DIAGNOSIS_PRESENT)
            # -------------------------------------------------------------------------
            rule_4_id = "RULE_004_DIAGNOSIS_PRESENT"
            rule_4_name = "Medical Diagnosis Presence Check"
            rule_4_expected = "diagnosis must be present and non-empty"
            rule_4_input = {"diagnosis": diagnosis}

            if not diagnosis or not str(diagnosis).strip():
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_4_id,
                        rule_name=rule_4_name,
                        input_values=rule_4_input,
                        expected_condition=rule_4_expected,
                        actual_value=diagnosis,
                        result="MISSING_DATA",
                        reason="Medical diagnosis is missing from extracted claim information.",
                    )
                )
            else:
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_4_id,
                        rule_name=rule_4_name,
                        input_values=rule_4_input,
                        expected_condition=rule_4_expected,
                        actual_value=str(diagnosis).strip(),
                        result="PASS",
                        reason=f"Medical diagnosis '{diagnosis}' present.",
                    )
                )

            # -------------------------------------------------------------------------
            # RULE 5: Incident / Service Date Check (RULE_005_CLAIM_DATE_VALID)
            # -------------------------------------------------------------------------
            rule_5_id = "RULE_005_CLAIM_DATE_VALID"
            rule_5_name = "Incident / Service Date Check"
            rule_5_expected = "date must be present and non-empty"
            rule_5_input = {"date": date_val}

            if not date_val or not str(date_val).strip():
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_5_id,
                        rule_name=rule_5_name,
                        input_values=rule_5_input,
                        expected_condition=rule_5_expected,
                        actual_value=date_val,
                        result="MISSING_DATA",
                        reason="Incident / service date is missing from extracted claim information.",
                    )
                )
            else:
                evaluated_rules.append(
                    RuleResult(
                        rule_id=rule_5_id,
                        rule_name=rule_5_name,
                        input_values=rule_5_input,
                        expected_condition=rule_5_expected,
                        actual_value=str(date_val).strip(),
                        result="PASS",
                        reason=f"Claim date '{date_val}' is present.",
                    )
                )

            # -------------------------------------------------------------------------
            # Decision Rollup Calculation
            # -------------------------------------------------------------------------
            passed_count = sum(1 for r in evaluated_rules if r.result == "PASS")
            failed_count = sum(1 for r in evaluated_rules if r.result == "FAIL")
            missing_count = sum(1 for r in evaluated_rules if r.result == "MISSING_DATA")
            total_count = len(evaluated_rules)

            if failed_count > 0:
                decision = "REJECTED"
                decision_reason = f"Claim rejected: {failed_count} deterministic rule(s) failed evaluation."
            elif missing_count > 0:
                decision = "FLAGGED_FOR_REVIEW"
                decision_reason = f"Claim flagged for manual review: {missing_count} required field(s) missing."
            else:
                decision = "APPROVED"
                decision_reason = f"All {passed_count} deterministic claim validation rules passed successfully."

            created_time = datetime.now(timezone.utc).isoformat()

            decision_obj = RuleEngineDecision(
                claim_id=claim_id,
                execution_id=str(execution_id),
                decision=decision,
                decision_reason=decision_reason,
                total_rules=total_count,
                passed_rules=passed_count,
                failed_rules=failed_count,
                missing_data_rules=missing_count,
                evaluated_rules=evaluated_rules,
                created_at=created_time,
            )

            span.set_attribute("rules.total_count", total_count)
            span.set_attribute("rules.passed_count", passed_count)
            span.set_attribute("rules.failed_count", failed_count)
            span.set_attribute("rules.missing_count", missing_count)
            span.set_attribute("rules.overall_decision", decision)
            span.set_attribute(OUTPUT_ARTIFACT_IDS, [f"art_decision_claim_{claim_id}"])

            # -------------------------------------------------------------------------
            # Database Persistence
            # -------------------------------------------------------------------------
            if db_session is not None:
                try:
                    _save_rule_evaluation_record(db=db_session, decision=decision_obj)
                except Exception as db_err:
                    logger.error(f"Failed to persist RuleEvaluationRecord to database: {db_err}")

            return decision_obj

        except Exception:
            raise


def _save_rule_evaluation_record(db: Any, decision: RuleEngineDecision):
    """
    Persists RuleEvaluationRecord in the database.
    """
    from app.models.rule_evaluation_record import RuleEvaluationRecord

    record = RuleEvaluationRecord(
        claim_id=int(decision.claim_id) if str(decision.claim_id).isdigit() else decision.claim_id,
        execution_id=decision.execution_id,
        decision=decision.decision,
        decision_reason=decision.decision_reason,
        total_rules=decision.total_rules,
        passed_rules=decision.passed_rules,
        failed_rules=decision.failed_rules,
        missing_data_rules=decision.missing_data_rules,
        evaluated_rules=[r.model_dump() for r in decision.evaluated_rules],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(f"Saved RuleEvaluationRecord ID #{record.id} with decision '{decision.decision}' for Claim #{decision.claim_id}.")
