"""Deterministic output guardrails G1-G9 for untrusted explanation drafts (E5.2).

A draft (normally written by an LLM) only words the existing diagnosis. These pure
functions decide whether a draft may be published. They never read the network,
the clock or randomness, and never change the bundle or the diagnosis.

Rule -> code map (see planning/03_architecture/27_explanation_llm_guardrails.md):

    G1 schema        _check_schema         draft parses and matches DRAFT_SCHEMA
    G2 evidence      _check_evidence       evidence_ids exist in the bundle; >=1 per item
    G3 about         _check_about          `about` is a stage instance in the bundle
    G4 claim/role    _check_claims         claim_type matches the RCA role; free text
                                           does not call a non-origin the origin or
                                           deny a fault the core found
    G5 identifiers   _check_identifiers    stage / art_ / obs_ / ENUM tokens exist
    G6 literals      _check_literals       numbers and quoted strings appear in bundle
    G7 playbook      _check_playbooks      playbook_id was retrieved, or null
    G8 pii           _check_pii            no email / phone / 12-16 digit numbers
    G9 length        _check_lengths        length and count limits

Violation details never echo draft text, so a guardrail log is safe to persist.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from jsonschema import Draft202012Validator

from autopsy.explain.bundle import _mask


CLAIM_TYPES = ("origin", "propagation", "impact", "context")
ROLES_FOR_CLAIM = {
    "origin": frozenset({"origin"}),
    "propagation": frozenset({"propagated", "tainted"}),
    "impact": frozenset({"not_executed", "tainted", "propagated"}),
}

MAX_SUMMARY_CHARS = 400
MAX_NARRATIVE_ITEMS = 12
MAX_NARRATIVE_CHARS = 600
MAX_EVIDENCE_IDS = 12
MAX_ABOUT_CHARS = 200
MAX_REMEDIATION_ITEMS = 3
MAX_REMEDIATION_CHARS = 600

DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "narrative", "remediation"],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "narrative": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["about", "claim_type", "text", "evidence_ids"],
                "properties": {
                    "about": {"type": "string"},
                    "claim_type": {"type": "string", "enum": list(CLAIM_TYPES)},
                    "text": {"type": "string", "minLength": 1},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "remediation": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "playbook_id"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "playbook_id": {"type": ["string", "null"]},
                },
            },
        },
    },
}
_SCHEMA_VALIDATOR = Draft202012Validator(DRAFT_SCHEMA)


@dataclass(frozen=True)
class Violation:
    code: str     # "G1".."G9"
    path: str     # e.g. "narrative[0].text"
    reason: str   # fixed vocabulary; never contains draft text

    def as_dict(self):
        return {"code": self.code, "path": self.path, "reason": self.reason}


# --- token patterns -----------------------------------------------------------

_QUOTED = re.compile(r'"([^"\n]{1,300})"|`([^`\n]{1,300})`|“([^”\n]{1,300})”')
_EVIDENCE_ID = re.compile(r"(?<![\w])(?:art|obs)_[A-Za-z0-9_]+(?![\w])")
_STAGE_INSTANCE = re.compile(r"(?<![\w.@-])[A-Za-z][\w-]*@[\w-]+(?![\w@-]|\.\w)")
_SNAKE = re.compile(r"(?<![\w.@-])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![\w@-]|\.\w)")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w)")
_ANY_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")
_ORIGIN_CLAIM = re.compile(r"\b(?:origin(?:ated|ates)?|root[\s-]+cause[sd]?)\b", re.I)
_NEGATION = re.compile(r"\b(?:no|not|cannot|unable|insufficient|without|unclear|"
                       r"undetermined|unknown|isn't|wasn't|doesn't|didn't|never)\b|n't\b", re.I)
_DENIES_FAULT = re.compile(
    r"\b(?:no\s+(?:pipeline\s+)?(?:faults?|issues?|problems?|failures?|errors?)\s+"
    r"(?:was|were)?\s*(?:found|detected|identified|occurred)|"
    r"(?:run|pipeline|everything)\s+(?:is|was)\s+healthy|nothing\s+(?:failed|went\s+wrong))\b",
    re.I,
)


# --- bundle index ------------------------------------------------------------

class _BundleIndex:
    """Lookup tables derived from the trusted evidence bundle."""

    def __init__(self, bundle):
        bundle = bundle if isinstance(bundle, dict) else {}
        self.findings = [f for f in bundle.get("findings") or [] if isinstance(f, dict)]
        self.role_by_stage = {}
        self.stages = set()
        self.evidence_ids = set()
        vocabulary = set()
        for finding in self.findings:
            stage = finding.get("stage")
            if isinstance(stage, str) and stage:
                self.stages.add(stage)
                self.role_by_stage.setdefault(stage, finding.get("role"))
            for key in ("role", "classification", "confidence", "severity"):
                if isinstance(finding.get(key), str):
                    vocabulary.add(finding[key])
            for row in finding.get("observations") or []:
                if not isinstance(row, dict):
                    continue
                if isinstance(row.get("stage"), str) and row["stage"]:
                    self.stages.add(row["stage"])
                for key in ("id", "artifact_id"):
                    if isinstance(row.get(key), str) and row[key]:
                        self.evidence_ids.add(row[key])
                for key in ("code", "field", "result"):
                    if isinstance(row.get(key), str):
                        vocabulary.add(row[key])
        for excerpt in bundle.get("excerpts") or []:
            if isinstance(excerpt, dict):
                if isinstance(excerpt.get("artifact_id"), str) and excerpt["artifact_id"]:
                    self.evidence_ids.add(excerpt["artifact_id"])
                for key in ("kind", "field"):
                    if isinstance(excerpt.get(key), str):
                        vocabulary.add(excerpt[key])
        self.playbook_ids = {row.get("playbook_id") for row in bundle.get("remediation") or []
                             if isinstance(row, dict) and isinstance(row.get("playbook_id"), str)}
        self.verdict = bundle.get("verdict")
        for key in ("verdict", "trace_grade", "evidence_level"):
            if isinstance(bundle.get(key), str):
                vocabulary.add(bundle[key])
        self.stage_types = {stage.split("@", 1)[0] for stage in self.stages}
        self.origin_stages = {stage for stage, role in self.role_by_stage.items() if role == "origin"}
        self.origin_types = {stage.split("@", 1)[0] for stage in self.origin_stages}
        vocabulary |= self.stages | self.stage_types | self.evidence_ids | self.playbook_ids
        self.vocabulary = {token.casefold() for token in vocabulary if token}

        # G6 corpus: every string and number in the bundle, including excerpt text.
        leaves = []
        _collect_leaves(bundle, leaves)
        for leaf in list(leaves):
            if "_" in leaf:
                leaves.append(leaf.replace("_", " "))
        self.corpus = _normalize("\n".join(leaves))
        self.numbers = {_number_key(token) for leaf in leaves for token in _ANY_NUMBER.findall(leaf)}
        self._stage_patterns = [
            (name, re.compile(rf"(?<![\w@-]){re.escape(name)}(?![\w@-])"))
            for name in sorted(self.stages | self.stage_types, key=len, reverse=True)
        ]

    def known_identifier(self, token):
        return token.casefold() in self.vocabulary

    def mentioned_stages(self, text):
        return {name for name, pattern in self._stage_patterns if pattern.search(text)}

    def blank_stage_instances(self, text):
        for name, pattern in self._stage_patterns:
            if "@" in name:
                text = pattern.sub(" ", text)
        return text

    def is_origin_mention(self, name):
        return name in self.origin_stages or name in self.origin_types


def _collect_leaves(value, out):
    if isinstance(value, dict):
        for item in value.values():
            _collect_leaves(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_leaves(item, out)
    elif isinstance(value, bool) or value is None:
        return
    else:
        out.append(str(value))


def _normalize(text):
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def _number_key(token):
    try:
        return Decimal(token).normalize()
    except InvalidOperation:
        return token


def _strip_quotes(text):
    return _QUOTED.sub(" ", text)


def _quoted(text):
    return [next(group for group in match.groups() if group is not None)
            for match in _QUOTED.finditer(text)]


# --- draft traversal ---------------------------------------------------------

def _texts(draft):
    """Yield (path, text) for every well-typed free-text field of a draft."""
    if isinstance(draft.get("summary"), str):
        yield "summary", draft["summary"]
    for index, item in enumerate(_items(draft, "narrative")):
        if isinstance(item.get("text"), str):
            yield f"narrative[{index}].text", item["text"]
    for index, item in enumerate(_items(draft, "remediation")):
        if isinstance(item.get("text"), str):
            yield f"remediation[{index}].text", item["text"]


def _items(draft, key):
    value = draft.get(key)
    if not isinstance(value, list):
        return []
    return [item if isinstance(item, dict) else {} for item in value]


# --- checks ------------------------------------------------------------------

def _check_schema(draft, index):
    out = []
    for error in sorted(_SCHEMA_VALIDATOR.iter_errors(draft), key=lambda e: list(e.absolute_path)):
        path = _format_path(error.absolute_path) or "$"
        out.append(Violation("G1", path, f"schema:{error.validator}"))
    return out


def _format_path(parts):
    path = ""
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path


def _check_evidence(draft, index):
    out = []
    for i, item in enumerate(_items(draft, "narrative")):
        ids = item.get("evidence_ids")
        if not isinstance(ids, list):
            continue
        valid_ids = [value for value in ids if isinstance(value, str)]
        if not valid_ids:
            out.append(Violation("G2", f"narrative[{i}].evidence_ids", "no_evidence"))
        for j, value in enumerate(valid_ids):
            if value not in index.evidence_ids:
                out.append(Violation("G2", f"narrative[{i}].evidence_ids[{j}]", "unknown_evidence_id"))
    return out


def _check_about(draft, index):
    out = []
    for i, item in enumerate(_items(draft, "narrative")):
        about = item.get("about")
        if isinstance(about, str) and about not in index.stages:
            out.append(Violation("G3", f"narrative[{i}].about", "unknown_stage"))
    return out


def _check_claims(draft, index):
    out = []
    for i, item in enumerate(_items(draft, "narrative")):
        about, claim = item.get("about"), item.get("claim_type")
        if not isinstance(about, str) or about not in index.stages or claim not in ROLES_FOR_CLAIM:
            continue
        if index.role_by_stage.get(about) not in ROLES_FOR_CLAIM[claim]:
            out.append(Violation("G4", f"narrative[{i}].claim_type", f"{claim}_claim_not_supported_by_role"))

    for path, text in _texts(draft):
        for sentence in _SENTENCE.split(text):
            if not _ORIGIN_CLAIM.search(sentence) or _NEGATION.search(sentence):
                continue
            mentions = index.mentioned_stages(sentence)
            unquoted = _strip_quotes(sentence)
            other_tokens = ({t for t in _STAGE_INSTANCE.findall(unquoted) if t not in index.stages}
                            | {t for t in _SNAKE.findall(unquoted) if t not in index.stage_types}
                            | {q for q in _quoted(sentence) if q not in index.stages | index.stage_types})
            if not index.origin_stages:
                if mentions or other_tokens:
                    out.append(Violation("G4", path, "origin_claim_without_core_origin"))
                    break
            elif not any(index.is_origin_mention(name) for name in mentions) and (mentions or other_tokens):
                out.append(Violation("G4", path, "origin_claim_contradicts_core"))
                break
        if path == "summary" and index.findings and index.verdict != "NO_ISSUE_DETECTED" \
                and _DENIES_FAULT.search(text):
            out.append(Violation("G4", path, "denies_core_findings"))
    return out


def _check_identifiers(draft, index):
    out = []
    for path, text in _texts(draft):
        unquoted = _strip_quotes(text)
        unknown = False
        for token in _EVIDENCE_ID.findall(unquoted):
            if token not in index.evidence_ids:
                unknown = True
        scrubbed = _EVIDENCE_ID.sub(" ", unquoted)
        for token in _STAGE_INSTANCE.findall(scrubbed) + _SNAKE.findall(_STAGE_INSTANCE.sub(" ", scrubbed)):
            if not index.known_identifier(token):
                unknown = True
        if unknown:
            out.append(Violation("G5", path, "unknown_identifier"))
    return out


def _check_literals(draft, index):
    out = []
    for path, text in _texts(draft):
        if any(_normalize(quote) not in index.corpus for quote in _quoted(text)):
            out.append(Violation("G6", path, "unsupported_quoted_string"))
        bare = _SNAKE.sub(" ", _STAGE_INSTANCE.sub(" ", _EVIDENCE_ID.sub(" ", _strip_quotes(text))))
        if any(_number_key(number) not in index.numbers for number in _NUMBER.findall(bare)):
            out.append(Violation("G6", path, "unsupported_number"))
    return out


def _check_playbooks(draft, index):
    out = []
    for i, item in enumerate(_items(draft, "remediation")):
        playbook_id = item.get("playbook_id")
        if isinstance(playbook_id, str) and playbook_id not in index.playbook_ids:
            out.append(Violation("G7", f"remediation[{i}].playbook_id", "playbook_not_retrieved"))
    return out


def contains_pii(text):
    """True when the bundle's configured PII masking would change the text."""
    return _mask(text) != str(text)


def _check_pii(draft, index):
    fields = list(_texts(draft))
    for i, item in enumerate(_items(draft, "narrative")):
        if isinstance(item.get("about"), str):
            fields.append((f"narrative[{i}].about", item["about"]))
    # Known `stage@item` instances look like bare e-mail addresses; blank them first.
    return [Violation("G8", path, "pii_pattern") for path, text in fields
            if contains_pii(index.blank_stage_instances(text))]


def _check_lengths(draft, index):
    out = []
    if isinstance(draft.get("summary"), str) and len(draft["summary"]) > MAX_SUMMARY_CHARS:
        out.append(Violation("G9", "summary", "too_long"))
    narrative = draft.get("narrative")
    if isinstance(narrative, list) and len(narrative) > MAX_NARRATIVE_ITEMS:
        out.append(Violation("G9", "narrative", "too_many_items"))
    for i, item in enumerate(_items(draft, "narrative")):
        if isinstance(item.get("text"), str) and len(item["text"]) > MAX_NARRATIVE_CHARS:
            out.append(Violation("G9", f"narrative[{i}].text", "too_long"))
        if isinstance(item.get("about"), str) and len(item["about"]) > MAX_ABOUT_CHARS:
            out.append(Violation("G9", f"narrative[{i}].about", "too_long"))
        if isinstance(item.get("evidence_ids"), list) and len(item["evidence_ids"]) > MAX_EVIDENCE_IDS:
            out.append(Violation("G9", f"narrative[{i}].evidence_ids", "too_many_items"))
    remediation = draft.get("remediation")
    if isinstance(remediation, list) and len(remediation) > MAX_REMEDIATION_ITEMS:
        out.append(Violation("G9", "remediation", "too_many_items"))
    for i, item in enumerate(_items(draft, "remediation")):
        if isinstance(item.get("text"), str) and len(item["text"]) > MAX_REMEDIATION_CHARS:
            out.append(Violation("G9", f"remediation[{i}].text", "too_long"))
    return out


CHECKS = (
    ("G1", _check_schema), ("G2", _check_evidence), ("G3", _check_about),
    ("G4", _check_claims), ("G5", _check_identifiers), ("G6", _check_literals),
    ("G7", _check_playbooks), ("G8", _check_pii), ("G9", _check_lengths),
)


def parse_draft(raw):
    """Return (draft_dict_or_None, violations) for a raw JSON string or a mapping."""
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, [Violation("G1", "$", "not_json")]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None, [Violation("G1", "$", "not_json")]
    if not isinstance(raw, dict):
        return None, [Violation("G1", "$", "not_an_object")]
    return raw, []


def validate_draft(raw, bundle):
    """Run G1-G9 on an untrusted draft; return every violation in rule order.

    An empty list means the draft may be published. If the draft is not a JSON
    object at all, only the G1 violation is returned; otherwise every rule runs on
    the parts of the draft that are well-typed, so all applicable violations show.
    """
    draft, violations = parse_draft(raw)
    if draft is None:
        return violations
    index = _BundleIndex(bundle)
    seen = set()
    for _, check in CHECKS:
        for violation in check(draft, index):
            if violation not in seen:
                seen.add(violation)
                violations.append(violation)
    return violations


def violation_codes(violations):
    return sorted({violation.code for violation in violations}, key=lambda code: int(code[1:]))


__all__ = [
    "CHECKS", "CLAIM_TYPES", "DRAFT_SCHEMA", "MAX_NARRATIVE_CHARS", "MAX_NARRATIVE_ITEMS",
    "MAX_REMEDIATION_CHARS", "MAX_REMEDIATION_ITEMS", "MAX_SUMMARY_CHARS", "ROLES_FOR_CLAIM",
    "Violation", "contains_pii", "parse_draft", "validate_draft", "violation_codes",
]
