"""Evidence excerpting and lightweight PII masking for producer uploads."""
import re


_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)\+?(?:\d[\s().-]*){7,15}\d?(?!\w)")
_ID_NUMBER = re.compile(r"(?<!\d)\d{12,16}(?!\d)")


def redact(text):
    """Mask email addresses, phone numbers, and 12–16 digit identifiers."""
    text = _EMAIL.sub("[REDACTED]", str(text))

    def mask_phone(match):
        digits = sum(char.isdigit() for char in match.group(0))
        return "[REDACTED]" if 7 <= digits <= 15 else match.group(0)

    return _ID_NUMBER.sub("[REDACTED]", _PHONE.sub(mask_phone, text))


def excerpt(content, values, radius=80):
    """Select source line snippets around extracted values and redact PII."""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    values = [str(value) for value in (values or []) if value is not None and str(value)]
    if not values:
        return ""
    snippets = []
    for line in text.splitlines():
        for value in values:
            start = line.find(value)
            if start >= 0:
                left = max(0, start - radius)
                right = min(len(line), start + len(value) + radius)
                snippet = line[left:right]
                if snippet not in snippets:
                    snippets.append(snippet)
    return redact("\n".join(snippets))
