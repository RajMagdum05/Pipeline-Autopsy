"""Pure implementations of the v1 insurance adjudication rules."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence

from app.adjudication.schemas import InputReference, RuleResult
from app.information_extraction.content_service import DEFAULT_CURRENCY_TOLERANCES
from app.information_extraction.schemas import REPEATABLE_FIELDS


@dataclass(frozen=True)
class FactValue:
    value: Any | None
    reference: InputReference
    unavailable_reason: str | None = None


class FactSet:
    """Read one field from either an extracted-facts payload or a plain mapping."""

    def __init__(self, document: Mapping[str, Any], *, document_id: str | None = None):
        self.document = document
        self.document_id = str(document_id or document.get("document_id") or document.get("id") or "unknown")
        facts = document.get("facts")
        self.facts = list(facts) if isinstance(facts, Sequence) and not isinstance(facts, (str, bytes)) else None

    def one(self, field: str, *, allow_repeatable: bool = False) -> FactValue:
        reference = InputReference(document_id=self.document_id, field=field)
        if self.facts is None:
            value = self.document.get(field)
            if value is None or value == "":
                return FactValue(None, reference, "missing")
            return FactValue(value, reference)

        rows = [row for row in self.facts if isinstance(row, Mapping) and row.get("field_name") == field]
        conflicting = [row for row in rows if row.get("field_status") == "conflicting"]
        if conflicting:
            return FactValue(None, reference, "conflicting")
        found = [row for row in rows if row.get("field_status") == "found"]
        if field in REPEATABLE_FIELDS and not allow_repeatable and found:
            return FactValue(None, reference, "repeatable")
        values = [row.get("normalized_value") or row.get("raw_value") for row in found]
        values = [value for value in values if value is not None and value != ""]
        if not values:
            return FactValue(None, reference, "missing")
        distinct = {str(value) for value in values}
        if len(values) != 1 or len(distinct) != 1:
            return FactValue(None, reference, "repeated_or_conflicting")
        return FactValue(values[0], reference)

    def many(self, field: str) -> tuple[list[Any], InputReference, str | None]:
        """Return found repeatable values, while rejecting declared conflicts."""
        reference = InputReference(document_id=self.document_id, field=field)
        if self.facts is None:
            raw = self.document.get(field)
            if raw is None or raw == "":
                return [], reference, "missing"
            values = raw if isinstance(raw, (list, tuple)) else [raw]
            return list(values), reference, None
        rows = [row for row in self.facts if isinstance(row, Mapping) and row.get("field_name") == field]
        if any(row.get("field_status") == "conflicting" for row in rows):
            return [], reference, "conflicting"
        values = [row.get("normalized_value") or row.get("raw_value") for row in rows if row.get("field_status") == "found"]
        values = [value for value in values if value is not None and value != ""]
        return values, reference, None if values else "missing"


def normalize_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def normalize_identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def canonical_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def decimal_value(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, bool) or value is None:
        return None
    cleaned = str(value).strip()
    cleaned = re.sub(r"^(?:INR|USD|EUR|GBP|JPY)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("₹", "").replace("$", "").replace("€", "").replace("£", "").strip()
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", cleaned):
        return None
    try:
        amount = Decimal(cleaned.replace(",", ""))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def currency_tolerance(currency: str, tolerances: Mapping[str, str | Decimal] = DEFAULT_CURRENCY_TOLERANCES) -> Decimal | None:
    value = tolerances.get(currency.upper())
    if value is None:
        return None
    amount = decimal_value(value)
    return amount if amount is not None and amount >= 0 else None


def make_result(rule_id: str, result: str, inputs: Sequence[InputReference], *,
                consequence: str | None = None, reason_code: str | None = None) -> RuleResult:
    return RuleResult(rule_id=rule_id, result=result, consequence=consequence,
                      inputs=tuple(dict.fromkeys(inputs)), reason_code=reason_code)
