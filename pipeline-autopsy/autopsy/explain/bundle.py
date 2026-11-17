"""Build a bounded evidence bundle from diagnosis findings and E2 artifacts."""

import json
import re


_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)\+?(?:\d[\s().-]*){7,15}\d?(?!\w)")
_LONG_ID = re.compile(r"(?<!\d)\d{12,16}(?!\d)")
_DATE = re.compile(r"\b(?:(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/](?:19|20)\d{2})\b")


def _mask(text):
    text = _EMAIL.sub("[REDACTED]", str(text))
    dates = []

    def hold_date(match):
        dates.append(match.group(0))
        return f"[DATE{len(dates)}]"

    text = _DATE.sub(hold_date, text)

    def mask_phone(match):
        digits = sum(char.isdigit() for char in match.group(0))
        return "[REDACTED]" if 7 <= digits <= 15 else match.group(0)

    text = _LONG_ID.sub("[REDACTED]", _PHONE.sub(mask_phone, text))
    for index, date in enumerate(dates, start=1):
        text = text.replace(f"[DATE{index}]", date)
    return text


def _value(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _artifact_text(artifact, field):
    content = artifact.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(page.get("text", "")) for page in content if isinstance(page, dict))
    if isinstance(content, dict):
        facts = content.get("facts")
        if isinstance(facts, list):
            selected = [fact for fact in facts if isinstance(fact, dict)
                        and (not field or fact.get("field_name") == field)]
            lines = []
            for fact in selected:
                value = fact.get("raw_value") or fact.get("normalized_value")
                if value:
                    lines.append(f"{fact.get('field_name', 'value')}: {value}")
                for evidence in fact.get("evidence", []):
                    if isinstance(evidence, dict) and evidence.get("quote"):
                        lines.append(str(evidence["quote"]))
            return "\n".join(dict.fromkeys(lines))
        return _value(content)
    return ""


def build_bundle(result, artifacts, evidence_level="E1", *, max_excerpt_chars=300,
                 max_excerpts=12):
    """Build factual explanation inputs; never include non-E2 or unredacted blobs."""
    observations = result.get("observations", [])
    findings = result.get("findings", [])
    observation_by_id = {observation.id: observation for observation in observations}
    excerpts = []
    excerpt_by_key = {}
    finding_rows = []

    for finding in findings:
        related = [observation_by_id[identifier] for identifier in finding.get("evidence", [])
                   if identifier in observation_by_id]
        finding_row = {
            "stage": finding.get("stage"), "role": finding.get("role"),
            "classification": finding.get("classification"),
            "confidence": finding.get("confidence"), "severity": finding.get("severity"),
            "observations": [{
                "id": observation.id, "code": observation.code,
                "result": observation.result, "stage": observation.stage,
                "artifact_id": observation.artifact_id, "field": observation.field,
                "detail": _mask(observation.detail)[:300],
            } for observation in related],
            "excerpts": [],
        }
        for observation in related:
            artifact_id = observation.artifact_id
            artifact = artifacts.get(artifact_id) if artifact_id else None
            if (evidence_level != "E2" or not artifact or not artifact.get("redacted")
                    or len(excerpts) >= max_excerpts):
                continue
            key = (artifact_id, observation.field)
            excerpt_id = excerpt_by_key.get(key)
            if excerpt_id is None:
                text = _mask(_artifact_text(artifact, observation.field)).strip()
                if not text:
                    continue
                excerpt_id = len(excerpts)
                excerpt_by_key[key] = excerpt_id
                excerpts.append({
                    "artifact_id": artifact_id, "kind": artifact.get("kind"),
                    "field": observation.field, "text": text[:max_excerpt_chars],
                })
            finding_row["excerpts"].append(excerpt_id)
        finding_rows.append(finding_row)

    return {
        "verdict": result.get("verdict"),
        "trace_grade": result.get("trace_grade"),
        "evidence_level": evidence_level,
        "findings": finding_rows,
        "excerpts": excerpts,
    }


__all__ = ["build_bundle"]
