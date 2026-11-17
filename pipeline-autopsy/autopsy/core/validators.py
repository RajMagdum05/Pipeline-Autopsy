import json
from typing import Callable, Dict


def v_grounded_fields(content, source, rule):
    text = json.dumps(source, ensure_ascii=False) if not isinstance(source, str) else source
    res = []
    for f in rule["fields"]:
        if f not in content or content[f] in (None, ""):
            continue
        res.append((f, str(content[f]) in text, f"value {content[f]!r}"))
    return res

def v_equals_upstream(content, source, rule):
    res = []
    for f in rule["fields"]:
        if f in content and f in source:
            res.append((f, content[f] == source[f], f"{content[f]!r} vs upstream {source[f]!r}"))
    return res


VALIDATORS: Dict[str, Callable] = {
    "grounded_fields": v_grounded_fields,
    "equals_upstream": v_equals_upstream,
}
