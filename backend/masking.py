"""Minimal PII masking, standing in for Maia's Phileas-based ProtectionService.

Masks Singapore NRIC/FIN numbers, Singapore phone numbers and email addresses
before any text reaches the model. Regex only: good enough for a POC, not a
replacement for the production service.
"""

import re

_PATTERNS = [
    ("NRIC", re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+65[\s-]?)?[3689]\d{3}[\s-]?\d{4}(?!\d)")),
]


def mask(text: str) -> str:
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text
