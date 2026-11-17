"""Deterministic prose for a diagnosis evidence bundle."""


def build_template(bundle):
    findings = bundle.get("findings", [])
    origins = [finding for finding in findings if finding.get("role") == "origin"]
    verdict = bundle.get("verdict", "INSUFFICIENT_EVIDENCE")
    grade = bundle.get("trace_grade", "C")
    if not findings:
        summary = f"No pipeline fault was identified (trace grade {grade})."
    elif not origins:
        summary = f"The run has downstream impact, but the available evidence does not isolate a root cause (trace grade {grade})."
    elif len(origins) == 1:
        origin = origins[0]
        classification = (origin.get("classification") or "UNCLASSIFIED").replace("_", " ").lower()
        confidence = origin.get("confidence") or "unknown"
        evidence_codes = [row.get("code") for row in origin.get("observations", []) if row.get("code")]
        evidence_text = ", ".join(dict.fromkeys(evidence_codes))
        summary = (f"Origin: {origin.get('stage') or 'unknown stage'} — {classification} "
                   f"({confidence} confidence).")
        if evidence_text:
            summary += f" Evidence: {evidence_text}."
    else:
        stages = ", ".join(finding.get("stage") or "unknown stage" for finding in origins)
        summary = f"The run has {len(origins)} independent origins: {stages} (trace grade {grade})."
    summary = summary[:400]

    excerpts = bundle.get("excerpts", [])
    narrative = []
    for finding in findings[:12]:
        stage = finding.get("stage") or "unknown stage"
        role = finding.get("role") or "unclassified"
        classification = finding.get("classification")
        line = f"{stage}: {role}"
        if classification:
            line += f" — {classification.replace('_', ' ').lower()}"
        if finding.get("confidence"):
            line += f" ({finding['confidence']} confidence)"
        observations = finding.get("observations", [])
        codes = list(dict.fromkeys(row.get("code") for row in observations if row.get("code")))
        if codes:
            line += ". Checks: " + ", ".join(codes)
        selected = [excerpts[index]["text"] for index in finding.get("excerpts", [])
                    if isinstance(index, int) and 0 <= index < len(excerpts)]
        if selected:
            line += ". Evidence excerpt: " + " | ".join(selected[:2])
        narrative.append(line[:600])
    if "remediation" not in bundle:
        remediation = []
    else:
        remediation = bundle["remediation"] or [{
            "playbook_id": None, "title": "No playbook for this pattern yet",
            "body": "No curated remediation matches this finding.", "pack": None, "score": 0,
        }]
    return {"source": "template", "summary": summary,
            "narrative": narrative, "remediation": remediation}


__all__ = ["build_template"]
