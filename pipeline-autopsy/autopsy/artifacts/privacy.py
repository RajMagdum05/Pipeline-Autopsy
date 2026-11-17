"""Small, dependency-free PII mask for artifact reads."""
import re


_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)\+?(?:\d[\s().-]*){7,15}\d?(?!\w)")
_ID_NUMBER = re.compile(r"(?<!\d)\d{12,16}(?!\d)")


def mask_text(value):
    text = str(value)
    text = _EMAIL.sub("[REDACTED]", text)

    def mask_phone(match):
        digits = sum(char.isdigit() for char in match.group(0))
        return "[REDACTED]" if 7 <= digits <= 15 else match.group(0)

    return _ID_NUMBER.sub("[REDACTED]", _PHONE.sub(mask_phone, text))


def mask_json(value):
    if isinstance(value, dict):
        return {key: mask_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_json(item) for item in value]
    if isinstance(value, str):
        return mask_text(value)
    return value
